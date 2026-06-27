from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from companies.models import Company
from products.models import Product, StockMovement
from sales.models import Sale, SaleItem


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

    def recalculate_total(self):
        total = Decimal("0.00")

        for item in self.items.all():
            total += item.total_price

        self.total_amount = total
        self.save(update_fields=["total_amount"])

    def approve(self, payment_method, user=None):
        if self.status in ["sold", "delivered"]:
            return self.sale

        if self.status in ["cancelled", "discarded"]:
            return None

        sale = Sale.objects.create(
            company=self.company,
            payment_method=payment_method,
            created_by=user,
        )

        for item in self.items.all():
            SaleItem.objects.create(
                sale=sale,
                company=self.company,
                product=item.product,
                quantity=item.quantity,
            )

        self.status = "sold"
        self.approved_by = user
        self.approved_at = timezone.now()
        self.sale = sale

        self.save(
            update_fields=[
                "status",
                "approved_by",
                "approved_at",
                "sale",
            ]
        )

        return sale

    def mark_delivered(self):
        if self.status != "sold":
            return

        self.status = "delivered"
        self.delivered_at = timezone.now()

        self.save(update_fields=["status", "delivered_at"])

    def cancel(self):
        """
        Cancela apenas pedidos em pré-venda.
        Não mexe no estoque porque ainda não virou venda.
        """
        if self.status != "pre_sale":
            return

        self.status = "cancelled"
        self.save(update_fields=["status"])

    def cancel_paid_and_return_stock(self, user=None):
        """
        Cancela um pedido já vendido e devolve os itens ao estoque.
        Use quando o pedido foi pago, mas os produtos não foram entregues/consumidos.
        """
        if self.status not in ["sold", "delivered"]:
            return

        if not self.sale:
            return

        for item in self.sale.items.all():
            StockMovement.objects.create(
                company=self.company,
                product=item.product,
                movement_type="return_to_stock",
                quantity=item.quantity,
                sale_value=0,
                cost_value=item.total_cost,
                reason=f"Cancelamento do Pedido #{self.id} com retorno ao estoque",
                created_by=user,
            )

        self.sale.status = "cancelled"
        self.sale.save(update_fields=["status"])

        self.status = "cancelled"
        self.save(update_fields=["status"])

    def discard_paid_order(self, user=None):
        """
        Descarta um pedido já vendido sem devolver estoque.
        Use quando houve erro no preparo, queda, perda ou descarte após pagamento.
        """
        if self.status not in ["sold", "delivered"]:
            return

        if self.sale:
            self.sale.status = "discarded"
            self.sale.save(update_fields=["status"])

        self.status = "discarded"
        self.save(update_fields=["status"])

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
        if self.company_id is None and self.order_id is not None:
            self.company = self.order.company

        if self.unit_price == 0:
            self.unit_price = self.product.sale_price

        self.total_price = self.quantity * self.unit_price

        super().save(*args, **kwargs)

        self.order.recalculate_total()

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"