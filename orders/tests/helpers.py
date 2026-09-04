from datetime import timedelta
from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import Profile
from companies.models import Company
from orders.models import Order, OrderItem
from products.category_services import resolve_category
from products.models import Product, StockEntry, Unit


D = Decimal
_sequence = count(1)


def unique(prefix):
    return f"{prefix}-{next(_sequence)}"


def make_company(*, name=None):
    return Company.objects.create(name=name or unique("Empresa"))


def make_user(*, company, role="owner", username=None):
    user = get_user_model().objects.create_user(
        username=username or unique("usuario"),
        password="test-password",
    )
    Profile.objects.create(user=user, company=company, role=role)
    return user


def make_unit(*, company, name=None, symbol=None):
    suffix = next(_sequence)
    return Unit.objects.create(
        company=company,
        name=name or f"Unidade {suffix}",
        symbol=symbol or f"u{suffix}",
    )


def make_product(
    *,
    company,
    unit=None,
    name=None,
    sale_price="10.00",
    product_type="sale",
    category=None,
    category_name="Testes",
    inventory_role="direct",
    sale_form="unit",
    stock_dimension="count",
    dose_ml=None,
    portion_g=None,
    preparation_mode=None,
):
    if category is None and category_name is not None:
        category = resolve_category(
            company=company,
            raw_name=category_name,
        )

    return Product.objects.create(
        company=company,
        unit=unit or make_unit(company=company),
        name=name or unique("Produto"),
        category=category,
        category_legacy=category.name if category else None,
        product_type=product_type,
        inventory_role=inventory_role,
        sale_form=sale_form,
        stock_dimension=stock_dimension,
        dose_ml=D(dose_ml) if dose_ml is not None else None,
        portion_g=D(portion_g) if portion_g is not None else None,
        preparation_mode=preparation_mode,
        sale_price=D(sale_price),
        minimum_quantity=D("0.00"),
        active=True,
    )


def make_entry(
    *,
    product,
    quantity,
    remaining=None,
    total_cost=None,
    company=None,
    created_at=None,
    created_by=None,
):
    quantity = D(quantity)
    entry = StockEntry.objects.create(
        company=company or product.company,
        product=product,
        total_cost=D(total_cost) if total_cost is not None else quantity,
        quantity_added=quantity,
        remaining_quantity=(
            D(remaining) if remaining is not None else quantity
        ),
        created_by=created_by,
    )
    if created_at is not None:
        StockEntry.objects.filter(pk=entry.pk).update(created_at=created_at)
        entry.refresh_from_db()
    return entry


def fifo_times():
    now = timezone.now()
    return now - timedelta(days=2), now - timedelta(days=1)


def make_order(*, company, lines, created_by=None, status="pre_sale"):
    order = Order.objects.create(
        company=company,
        status=status,
        created_by=created_by,
    )
    items = []
    for line in lines:
        product, quantity, *price = line
        item_kwargs = {
            "order": order,
            "company": company,
            "product": product,
            "quantity": D(quantity),
        }
        if price:
            item_kwargs["unit_price"] = D(price[0])
        items.append(OrderItem.objects.create(**item_kwargs))
    order.refresh_from_db()
    return order, items


class OrderTestMixin:
    def setUp(self):
        self.company = make_company()
        self.user = make_user(company=self.company)
        self.unit = make_unit(company=self.company)

    def make_product(self, **kwargs):
        kwargs.setdefault("company", self.company)
        kwargs.setdefault("unit", self.unit)
        return make_product(**kwargs)

    def make_order(self, lines, **kwargs):
        kwargs.setdefault("company", self.company)
        kwargs.setdefault("created_by", self.user)
        return make_order(lines=lines, **kwargs)
