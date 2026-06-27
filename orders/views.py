import json
from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import (
    can_access_pdv,
    can_approve_order,
    can_cancel_paid_order,
    can_cancel_pre_sale,
    can_create_order,
    can_discard_paid_order,
    can_mark_delivered,
    can_view_orders_panel,
    get_user_company,
)
from products.models import Product
from .models import Order, OrderItem


@login_required
def pdv_view(request):
    if not can_access_pdv(request.user):
        messages.warning(request, "Você não tem permissão para acessar o PDV.")
        return redirect("/admin/")

    company = get_user_company(request.user)

    if company is None:
        messages.warning(request, "Cadastre uma empresa antes de usar o PDV.")
        return redirect("/admin/companies/company/")

    if request.method == "POST":
        if not can_create_order(request.user):
            messages.warning(request, "Você não tem permissão para criar pedidos.")
            return redirect("orders:pdv")

        table_or_tab = request.POST.get("table_or_tab", "").strip()
        cart_data = request.POST.get("cart_data", "[]")

        try:
            cart_items = json.loads(cart_data)
        except json.JSONDecodeError:
            cart_items = []

        if not cart_items:
            messages.warning(request, "Adicione pelo menos um item ao pedido.")
            return redirect("orders:pdv")

        order = Order.objects.create(
            company=company,
            table_or_tab=table_or_tab,
            status="pre_sale",
            created_by=request.user,
        )

        for item in cart_items:
            product_id = item.get("id")
            quantity = Decimal(str(item.get("quantity", 1)))

            product = get_object_or_404(
                Product,
                id=product_id,
                company=company,
                active=True,
            )

            OrderItem.objects.create(
                order=order,
                company=company,
                product=product,
                quantity=quantity,
            )

        messages.success(request, f"Pedido #{order.id} enviado como pré-venda.")

        if can_view_orders_panel(request.user) or can_approve_order(request.user):
            return redirect("orders:order_detail", order_id=order.id)

        return redirect("orders:pdv")

    products = (
        Product.objects
        .filter(company=company, active=True)
        .select_related("unit")
        .order_by("category", "name")
    )

    categories = defaultdict(list)

    for product in products:
        category_name = product.category or "Sem categoria"
        categories[category_name].append(product)

    return render(
        request,
        "orders/pdv.html",
        {
            "company": company,
            "categories": dict(categories),
        },
    )


@login_required
def orders_panel(request):
    if not can_view_orders_panel(request.user):
        messages.warning(request, "Você não tem permissão para ver o painel de pedidos.")
        return redirect("orders:pdv")

    company = get_user_company(request.user)
    search_query = request.GET.get("q", "").strip()

    orders = (
        Order.objects
        .filter(company=company, status__in=["pre_sale", "sold", "delivered"])
        .select_related("company", "created_by", "approved_by", "sale")
        .prefetch_related("items__product")
        .order_by("-created_at")
    )

    if search_query:
        search_filter = (
            Q(created_by__username__icontains=search_query)
            | Q(created_by__first_name__icontains=search_query)
            | Q(created_by__last_name__icontains=search_query)
            | Q(items__product__name__icontains=search_query)
            | Q(table_or_tab__icontains=search_query)
        )

        numeric_query = "".join(character for character in search_query if character.isdigit())

        if numeric_query:
            search_filter |= Q(id=int(numeric_query))

        orders = orders.filter(search_filter).distinct()

    pre_sale_orders = orders.filter(status="pre_sale")
    preparing_orders = orders.filter(status="sold")
    delivered_orders = orders.filter(status="delivered")

    return render(
        request,
        "orders/orders_panel.html",
        {
            "search_query": search_query,
            "total_active_orders": orders.count(),
            "pre_sale_orders": pre_sale_orders,
            "pre_sale_count": pre_sale_orders.count(),
            "preparing_orders": preparing_orders,
            "preparing_count": preparing_orders.count(),
            "delivered_orders": delivered_orders,
            "delivered_count": delivered_orders.count(),
            "can_approve_order": can_approve_order(request.user),
            "can_mark_delivered": can_mark_delivered(request.user),
            "can_cancel_pre_sale": can_cancel_pre_sale(request.user),
            "can_cancel_paid_order": can_cancel_paid_order(request.user),
            "can_discard_paid_order": can_discard_paid_order(request.user),
        },
    )


@login_required
def order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects
        .select_related("company", "created_by", "approved_by", "sale")
        .prefetch_related("items__product"),
        id=order_id,
    )

    can_view_this_order = (
        can_view_orders_panel(request.user)
        or order.created_by_id == request.user.id
    )

    if not can_view_this_order:
        messages.warning(request, "Você não tem permissão para ver este pedido.")
        return redirect("orders:pdv")

    return render(
        request,
        "orders/order_detail.html",
        {
            "order": order,
            "can_approve_order": can_approve_order(request.user),
            "can_mark_delivered": can_mark_delivered(request.user),
            "can_cancel_pre_sale": can_cancel_pre_sale(request.user),
            "can_cancel_paid_order": can_cancel_paid_order(request.user),
            "can_discard_paid_order": can_discard_paid_order(request.user),
        },
    )


@login_required
@require_POST
def approve_order(request, order_id, payment_method):
    if not can_approve_order(request.user):
        messages.warning(request, "Você não tem permissão para aprovar vendas.")
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id)
    sale = order.approve(payment_method=payment_method, user=request.user)

    if sale:
        messages.success(request, f"Pedido #{order.id} aprovado com sucesso.")
    else:
        messages.warning(request, f"Pedido #{order.id} não pôde ser aprovado.")

    return redirect("orders:order_detail", order_id=order.id)


@login_required
@require_POST
def mark_order_delivered(request, order_id):
    if not can_mark_delivered(request.user):
        messages.warning(request, "Você não tem permissão para marcar pedidos como entregues.")
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id)
    order.mark_delivered()

    messages.success(request, f"Pedido #{order.id} marcado como entregue.")

    return redirect("orders:order_detail", order_id=order.id)


@login_required
@require_POST
def cancel_order(request, order_id):
    if not can_cancel_pre_sale(request.user):
        messages.warning(request, "Você não tem permissão para cancelar pré-vendas.")
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id)
    order.cancel()

    messages.warning(request, f"Pedido #{order.id} cancelado.")

    return redirect("orders:order_detail", order_id=order.id)


@login_required
@require_POST
def cancel_paid_order_with_stock_return(request, order_id):
    if not can_cancel_paid_order(request.user):
        messages.warning(
            request,
            "Você não tem permissão para cancelar vendas e devolver estoque.",
        )
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id)
    order.cancel_paid_and_return_stock(user=request.user)

    messages.warning(
        request,
        f"Pedido #{order.id} cancelado e itens retornados ao estoque.",
    )

    return redirect("orders:order_detail", order_id=order.id)


@login_required
@require_POST
def discard_paid_order(request, order_id):
    if not can_discard_paid_order(request.user):
        messages.warning(
            request,
            "Você não tem permissão para descartar vendas.",
        )
        return redirect("orders:order_detail", order_id=order_id)

    order = get_object_or_404(Order, id=order_id)
    order.discard_paid_order(user=request.user)

    messages.warning(
        request,
        f"Pedido #{order.id} descartado. Os itens não voltaram ao estoque.",
    )

    return redirect("orders:order_detail", order_id=order.id)
