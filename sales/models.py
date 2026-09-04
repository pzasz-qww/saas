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
    PHYSICAL_BASE_UNITS = [
        ("unit", "unidade"),
        ("g", "g"),
        ("mL", "mL"),
    ]

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="items")
    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)

    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Immutable commercial-to-physical conversion used by this specific sale.
    # Nullable fields keep pre-existing SaleItems explicitly compatible.
    sale_form_snapshot = models.CharField(
        max_length=20,
        choices=Product.SALE_FORMS,
        blank=True,
        null=True,
    )
    physical_quantity_per_sale_unit = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        blank=True,
        null=True,
    )
    physical_quantity_total = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        blank=True,
        null=True,
    )
    physical_base_unit = models.CharField(
        max_length=10,
        choices=PHYSICAL_BASE_UNITS,
        blank=True,
        null=True,
    )

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

        snapshot_values = (
            self.sale_form_snapshot,
            self.physical_quantity_per_sale_unit,
            self.physical_quantity_total,
            self.physical_base_unit,
        )
        populated_snapshot_values = sum(value is not None for value in snapshot_values)
        if populated_snapshot_values not in (0, len(snapshot_values)):
            raise ValidationError(
                "O retrato do consumo físico da venda está incompleto."
            )

        if populated_snapshot_values:
            if self.sale_form_snapshot not in dict(Product.SALE_FORMS):
                raise ValidationError("A forma de venda registrada é inválida.")
            if self.physical_base_unit not in dict(self.PHYSICAL_BASE_UNITS):
                raise ValidationError("A unidade física registrada é inválida.")
            for value, label in (
                (
                    self.physical_quantity_per_sale_unit,
                    "A quantidade física por unidade vendida",
                ),
                (self.physical_quantity_total, "A quantidade física total"),
            ):
                if not isinstance(value, Decimal):
                    try:
                        value = Decimal(str(value))
                    except (ArithmeticError, TypeError, ValueError):
                        raise ValidationError(f"{label} é inválida.") from None
                if not value.is_finite() or value <= 0:
                    raise ValidationError(f"{label} deve ser positiva.")

            expected_total = self.quantity * self.physical_quantity_per_sale_unit
            if self.physical_quantity_total != expected_total:
                raise ValidationError(
                    "A quantidade física total não corresponde à quantidade vendida."
                )

            if (
                self.sale_form_snapshot == "unit"
                and self.physical_quantity_per_sale_unit != Decimal("1")
            ):
                raise ValidationError(
                    "Vendas por unidade precisam consumir uma unidade física por item."
                )
            expected_base_unit = {
                "dose": "mL",
                "portion": "g",
            }.get(self.sale_form_snapshot)
            if expected_base_unit and self.physical_base_unit != expected_base_unit:
                raise ValidationError(
                    "A unidade física não corresponde à forma de venda registrada."
                )

            if self.pk:
                original_snapshot = (
                    type(self).objects.filter(pk=self.pk).values_list(
                        "sale_form_snapshot",
                        "physical_quantity_per_sale_unit",
                        "physical_quantity_total",
                        "physical_base_unit",
                    ).first()
                )
                if original_snapshot and original_snapshot != snapshot_values:
                    raise ValidationError(
                        "O retrato do consumo físico de uma venda não pode ser alterado."
                    )

        self.total_price = self.quantity * self.unit_price
        self.total_cost = self.quantity * self.unit_cost

        super().save(*args, **kwargs)

        self.sale.recalculate_totals()

    @property
    def stock_quantity_for_traceability(self):
        """Physical quantity for new rows; commercial fallback for legacy rows."""
        return self.physical_quantity_total or self.quantity

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"
