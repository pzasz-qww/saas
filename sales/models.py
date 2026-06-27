from decimal import Decimal

from django.conf import settings
from django.db import models

from companies.models import Company
from products.models import Product, StockMovement


class Sale(models.Model):
    PAYMENT_METHODS = [
        ("cash", "Dinheiro"),
        ("pix", "Pix"),
        ("debit", "Débito"),
        ("credit", "Crédito"),
        ("other", "Outro"),
    ]

    SALE_STATUS = [
        ("active", "Ativa"),
        ("cancelled", "Cancelada"),
        ("discarded", "Descartada"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)

    status = models.CharField(
        max_length=20,
        choices=SALE_STATUS,
        default="active",
    )

    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gross_profit = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Venda"
        verbose_name_plural = "Vendas"
        ordering = ["-created_at"]

    def recalculate_totals(self):
        total_amount = Decimal("0.00")
        total_cost = Decimal("0.00")

        for item in self.items.all():
            total_amount += item.total_price
            total_cost += item.total_cost

        self.total_amount = total_amount
        self.total_cost = total_cost
        self.gross_profit = total_amount - total_cost

        self.save(update_fields=["total_amount", "total_cost", "gross_profit"])

    def __str__(self):
        return f"Venda #{self.id} - R$ {self.total_amount}"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)

    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Item da venda"
        verbose_name_plural = "Itens da venda"

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if self.company_id is None and self.sale_id is not None:
            self.company = self.sale.company

        if self.unit_price == 0:
            self.unit_price = self.product.sale_price

        if self.unit_cost == 0:
            self.unit_cost = self.product.average_cost

        self.total_price = self.quantity * self.unit_price
        self.total_cost = self.quantity * self.unit_cost

        super().save(*args, **kwargs)

        if is_new:
            StockMovement.objects.create(
                company=self.company,
                product=self.product,
                movement_type="sale",
                quantity=self.quantity,
                sale_value=self.total_price,
                cost_value=self.total_cost,
                reason=f"Venda #{self.sale.id}",
                created_by=self.sale.created_by,
            )

        self.sale.recalculate_totals()

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"