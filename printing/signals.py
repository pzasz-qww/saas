"""Observe stable models; every printing write happens after their commit."""
import logging
from functools import partial

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ItemPrintContext, OrderPrintContext
from .services import enqueue_order


logger = logging.getLogger(__name__)


def after_commit(callback, *, using):
    def isolated():
        try:
            callback()
        except Exception:
            logger.exception("Falha isolada de impressão após commit; operação comercial preservada.")
    transaction.on_commit(isolated, using=using, robust=True)


def persist_context(model, *, using, lookup, defaults):
    model.objects.using(using).get_or_create(**lookup, defaults=defaults)


@receiver(post_save, sender="orders.Order", dispatch_uid="printing.capture_order_identity")
def order_created(sender, instance, created, raw=False, using="default", **kwargs):
    if raw or not created:
        return
    try:
        # A failed database read must not poison the surrounding order transaction.
        with transaction.atomic(using=using):
            from accounts.models import Profile
            profile = Profile.objects.using(using).select_related("user", "role_template").filter(user_id=instance.created_by_id, company_id=instance.company_id).first()
            defaults = {
                "employee_name": (profile.user.get_full_name() or profile.user.username) if profile else "Não registrado",
                "employee_role": profile.role_name() if profile else "Cargo não registrado",
            }
        after_commit(partial(persist_context, OrderPrintContext, using=using,
            lookup={"company_id": instance.company_id, "order_reference": instance.pk}, defaults=defaults), using=using)
    except Exception:
        logger.exception("Não foi possível capturar a identidade do pedido %s; pedido preservado.", instance.pk)


@receiver(post_save, sender="orders.OrderItem", dispatch_uid="printing.capture_item_name")
def item_saved(sender, instance, raw=False, using="default", **kwargs):
    if raw:
        return
    try:
        with transaction.atomic(using=using):
            from products.models import Product
            name = Product.objects.using(using).values_list("name", flat=True).get(pk=instance.product_id, company_id=instance.company_id)
        after_commit(partial(persist_context, ItemPrintContext, using=using,
            lookup={"company_id": instance.company_id, "order_reference": instance.order_id,
                    "item_reference": instance.pk, "product_reference": instance.product_id},
            defaults={"product_name": name}), using=using)
    except Exception:
        logger.exception("Não foi possível capturar o nome do item %s; item preservado.", instance.pk)


def enqueue_sale(*, sale_id, company_id, using):
    from orders.models import Order
    order_id = Order.objects.using(using).filter(sale_id=sale_id, company_id=company_id, status__in=["sold", "delivered"], sale__status="active").values_list("pk", flat=True).first()
    if order_id:
        enqueue_order(order_id=order_id, company_id=company_id, using=using)


@receiver(post_save, sender="sales.Sale", dispatch_uid="printing.sale_after_commit")
def sale_saved(sender, instance, raw=False, using="default", **kwargs):
    if raw or instance.status != "active":
        return
    try:
        after_commit(partial(enqueue_sale, sale_id=instance.pk, company_id=instance.company_id, using=using), using=using)
    except Exception:
        logger.exception("Não foi possível agendar impressão da venda %s; venda preservada.", instance.pk)
