from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from companies.models import Company
from products.models import Product


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

    def save(self, *args, **kwargs):
        valid_payment_methods = {
            value
            for value, _label in self.PAYMENT_METHODS
        }

        if self.payment_method not in valid_payment_methods:
            raise ValidationError("Forma de pagamento inválida.")

        super().save(*args, **kwargs)

    def recalculate_totals(self):
        total_amount = Decimal("0.00")
        total_cost = Decimal("0.00")

        for item in self.items.filter(
            company=self.company,
            product__company=self.company,
        ):
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
        if (
            self.quantity is None
            or not self.quantity.is_finite()
            or self.quantity <= 0
        ):
            raise ValidationError(
                "A quantidade do item deve ser maior que zero."
            )

        if self.sale_id is None:
            raise ValidationError("O item deve estar vinculado a uma venda.")

        if self.product_id is None:
            raise ValidationError("O item deve estar vinculado a um produto.")

        if self.company_id is None:
            self.company_id = self.sale.company_id

        if self.sale_id and self.company_id != self.sale.company_id:
            raise ValidationError("O item deve pertencer à mesma empresa da venda.")

        if self.product_id and self.company_id != self.product.company_id:
            raise ValidationError("O produto deve pertencer à mesma empresa da venda.")

        self.total_price = self.quantity * self.unit_price
        self.total_cost = self.quantity * self.unit_cost

        super().save(*args, **kwargs)

        self.sale.recalculate_totals()

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"
