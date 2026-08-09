from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, router, transaction
from django.db.models import Sum

from companies.models import Company
from products.models import Product
from sales.models import Sale


class Order(models.Model):
    STATUS_CHOICES = [
        ("pre_sale", "Pré-venda"),
        ("sold", "Vendido"),
        ("delivered", "Entregue"),
        ("cancelled", "Cancelado"),
        ("discarded", "Descartado"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    table_or_tab = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Mesa, comanda ou identificação do cliente.",
    )

    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="pre_sale",
    )

    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_orders",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="approved_orders",
    )

    approved_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)

    sale = models.OneToOneField(
        Sale,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="order",
    )

    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pedido"
        verbose_name_plural = "Pedidos"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if (
            self.sale_id
            and self.company_id
            and self.sale.company_id != self.company_id
        ):
            raise ValidationError(
                "A venda e o pedido devem pertencer à mesma empresa."
            )

        super().save(*args, **kwargs)

    def recalculate_total(self):
        total = Decimal("0.00")

        for item in self.items.filter(
            company=self.company,
            product__company=self.company,
        ):
            total += item.total_price

        self.total_amount = total
        self.save(update_fields=["total_amount"])

    def approve(self, payment_method, user=None):
        from .services import InvalidPaymentMethod, approve_order

        try:
            result = approve_order(
                order_id=self.pk,
                company=self.company,
                payment_method=payment_method,
                user=user,
            )
        except InvalidPaymentMethod as exc:
            raise ValidationError(str(exc)) from exc
        self.refresh_from_db()
        return result.sale

    def mark_delivered(self):
        from .services import mark_order_delivered

        mark_order_delivered(order_id=self.pk, company=self.company)
        self.refresh_from_db()

    def cancel(self):
        """
        Cancela apenas pedidos em pré-venda.
        Não mexe no estoque porque ainda não virou venda.
        """
        from .services import cancel_pre_sale_order

        cancel_pre_sale_order(order_id=self.pk, company=self.company)
        self.refresh_from_db()

    def cancel_paid_and_return_stock(self, user=None):
        """
        Cancela um pedido já vendido e devolve os itens ao estoque.
        Use quando o pedido foi pago, mas os produtos não foram entregues/consumidos.
        """
        from .services import cancel_paid_order_with_stock_return

        result = cancel_paid_order_with_stock_return(
            order_id=self.pk,
            company=self.company,
            user=user,
        )
        self.refresh_from_db()
        return result.restored

    def discard_paid_order(self, user=None):
        """
        Descarta um pedido já vendido sem devolver estoque.
        Use quando houve erro no preparo, queda, perda ou descarte após pagamento.
        """
        from .services import discard_paid_order

        discard_paid_order(
            order_id=self.pk,
            company=self.company,
            user=user,
        )
        self.refresh_from_db()

    def __str__(self):
        return f"Pedido #{self.id} - {self.get_status_display()} - R$ {self.total_amount}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)

    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    notes = models.CharField(max_length=120, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Item do pedido"
        verbose_name_plural = "Itens do pedido"

    def save(self, *args, **kwargs):
        if (
            self.quantity is None
            or not self.quantity.is_finite()
            or self.quantity <= 0
        ):
            raise ValidationError(
                "A quantidade do item deve ser maior que zero."
            )

        if self.order_id is None:
            raise ValidationError("O item deve estar vinculado a um pedido.")

        database = kwargs.get("using") or router.db_for_write(
            type(self),
            instance=self,
        )
        is_creation = self._state.adding

        with transaction.atomic(using=database):
            if not is_creation:
                persisted_order_id = (
                    type(self).objects.using(database)
                    .filter(pk=self.pk)
                    .values_list("order_id", flat=True)
                    .get()
                )
                if persisted_order_id != self.order_id:
                    raise ValidationError(
                        "Um item existente não pode ser transferido para outro pedido."
                    )

            locked_order = (
                Order.objects.using(database)
                .select_for_update()
                .get(pk=self.order_id)
            )

            if locked_order.status != "pre_sale":
                raise ValidationError(
                    "Itens só podem ser alterados enquanto o pedido está em pré-venda."
                )

            if not is_creation:
                persisted_item = (
                    type(self).objects.using(database)
                    .select_for_update()
                    .only("order_id")
                    .get(pk=self.pk)
                )
                if persisted_item.order_id != locked_order.pk:
                    raise ValidationError(
                        "O item foi alterado concorrentemente. Tente novamente."
                    )

            if self.company_id is None:
                self.company_id = locked_order.company_id

            if self.company_id != locked_order.company_id:
                raise ValidationError(
                    "O item deve pertencer à mesma empresa do pedido."
                )

            if self.product_id is None:
                raise ValidationError("O item deve estar vinculado a um produto.")

            product = (
                Product.objects.using(database)
                .only("company_id", "sale_price")
                .get(pk=self.product_id)
            )
            if self.company_id != product.company_id:
                raise ValidationError(
                    "O produto deve pertencer à mesma empresa do pedido."
                )

            if is_creation and self.unit_price == 0:
                self.unit_price = product.sale_price

            self.total_price = self.quantity * self.unit_price
            result = super().save(*args, **kwargs)
            self._recalculate_locked_order_total(locked_order, database)
            return result

    def delete(self, using=None, keep_parents=False):
        database = using or router.db_for_write(type(self), instance=self)

        with transaction.atomic(using=database):
            persisted_item = (
                type(self).objects.using(database)
                .filter(pk=self.pk)
                .values("pk", "order_id")
                .get()
            )
            locked_order = (
                Order.objects.using(database)
                .select_for_update()
                .get(pk=persisted_item["order_id"])
            )

            if locked_order.status != "pre_sale":
                raise ValidationError(
                    "Itens só podem ser excluídos enquanto o pedido está em pré-venda."
                )

            locked_item = (
                type(self).objects.using(database)
                .select_for_update()
                .get(pk=persisted_item["pk"])
            )
            result = super(OrderItem, locked_item).delete(
                using=database,
                keep_parents=keep_parents,
            )
            self.pk = None
            self._recalculate_locked_order_total(locked_order, database)
            return result

    @staticmethod
    def _recalculate_locked_order_total(locked_order, database):
        total = (
            OrderItem.objects.using(database)
            .filter(order_id=locked_order.pk)
            .aggregate(total=Sum("total_price"))["total"]
            or Decimal("0.00")
        )
        Order.objects.using(database).filter(pk=locked_order.pk).update(
            total_amount=total
        )

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"
