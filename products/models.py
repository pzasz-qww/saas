from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum

from companies.models import Company


class Unit(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    symbol = models.CharField(max_length=20)

    class Meta:
        verbose_name = "Unidade"
        verbose_name_plural = "Unidades"
        unique_together = ("company", "symbol")
        ordering = ["name"]

    def __str__(self):
        return self.symbol


class Product(models.Model):
    PRODUCT_TYPES = [
        ("sale", "Produto de venda"),
        ("internal_use", "Uso interno"),
        ("both", "Venda e uso interno"),
    ]
    STOCK_STATUS_LABELS = {
        "empty": "Esgotado",
        "critical": "Crítico",
        "low": "Baixo",
        "ok": "OK",
    }

    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    name = models.CharField(max_length=120)
    category = models.CharField(max_length=80, blank=True, null=True)
    product_type = models.CharField(max_length=30, choices=PRODUCT_TYPES, default="sale")

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)

    sale_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Preço cobrado por unidade vendida. Exemplo: R$ 28 por porção.",
    )

    active = models.BooleanField(default=True)

    minimum_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Quantidade mínima para alerta de estoque baixo.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Produto"
        verbose_name_plural = "Produtos"
        ordering = ["name"]

    @property
    def current_stock(self):
        annotated_stock = self._get_annotated_decimal(
            "annotated_current_stock",
            "report_current_stock",
        )

        if annotated_stock is not None:
            return annotated_stock

        result = self.stock_entries.aggregate(total=Sum("remaining_quantity"))
        return result["total"] or Decimal("0.00")

    def _get_annotated_decimal(self, *attribute_names):
        for attribute_name in attribute_names:
            if hasattr(self, attribute_name):
                return getattr(self, attribute_name) or Decimal("0.00")

        return None

    @classmethod
    def get_stock_status(cls, current_stock, recommended_quantity):
        current_stock = current_stock or Decimal("0.00")
        recommended_quantity = recommended_quantity or Decimal("0.00")
        half_recommended = recommended_quantity / Decimal("2")

        if current_stock <= 0:
            return "empty"

        if current_stock <= half_recommended:
            return "critical"

        if current_stock <= recommended_quantity:
            return "low"

        return "ok"

    @classmethod
    def get_stock_status_label(cls, current_stock, recommended_quantity):
        status = cls.get_stock_status(current_stock, recommended_quantity)
        return cls.STOCK_STATUS_LABELS[status]

    @property
    def stock_status(self):
        return self.get_stock_status(self.current_stock, self.minimum_quantity)

    @property
    def stock_status_label(self):
        return self.get_stock_status_label(self.current_stock, self.minimum_quantity)

    @property
    def average_cost(self):
        annotated_cost_total = self._get_annotated_decimal(
            "annotated_average_cost_total"
        )
        annotated_cost_quantity = self._get_annotated_decimal(
            "annotated_average_cost_quantity"
        )

        if annotated_cost_total is not None and annotated_cost_quantity is not None:
            if annotated_cost_quantity == 0:
                return Decimal("0.00")

            return annotated_cost_total / annotated_cost_quantity

        entries = self.stock_entries.filter(remaining_quantity__gt=0)

        total_cost = Decimal("0.00")
        total_quantity = Decimal("0.00")

        for entry in entries:
            total_cost += entry.remaining_quantity * entry.unit_cost
            total_quantity += entry.remaining_quantity

        if total_quantity == 0:
            return Decimal("0.00")

        return total_cost / total_quantity

    @property
    def profit_per_unit(self):
        return self.sale_price - self.average_cost

    @property
    def stock_value(self):
        return self.current_stock * self.average_cost

    @property
    def potential_revenue(self):
        return self.current_stock * self.sale_price

    @property
    def potential_profit(self):
        return self.potential_revenue - self.stock_value

    def __str__(self):
        return self.name


class StockEntry(models.Model):
    ENTRY_MODES = [
        ("simple", "Entrada simples"),
        ("detailed", "Entrada detalhada"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_entries",
    )

    entry_mode = models.CharField(max_length=20, choices=ENTRY_MODES, default="simple")

    total_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Valor total investido. Exemplo: R$ 150 em batata.",
    )

    quantity_added = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Quantidade gerada. Exemplo: 30 porções ou 24 unidades.",
    )

    remaining_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )

    package_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Opcional. Exemplo: 6 caixas, 3 sacos.",
    )

    package_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Opcional. Exemplo: R$ 25 por saco.",
    )

    notes = models.TextField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Entrada de estoque"
        verbose_name_plural = "Entradas de estoque"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.company_id is None and self.product_id is not None:
            self.company = self.product.company

        if (
            self.entry_mode == "detailed"
            and self.package_quantity
            and self.package_cost
        ):
            self.total_cost = self.package_quantity * self.package_cost

        if self.remaining_quantity is None:
            self.remaining_quantity = self.quantity_added

        super().save(*args, **kwargs)

    @property
    def unit_cost(self):
        if not self.quantity_added:
            return Decimal("0.00")

        return self.total_cost / self.quantity_added

    @property
    def potential_revenue(self):
        return self.quantity_added * self.product.sale_price

    @property
    def expected_profit(self):
        return self.potential_revenue - self.total_cost

    def __str__(self):
        return f"{self.product.name} - Entrada #{self.id}"


class StockMovement(models.Model):
    MOVEMENT_TYPES = [
        ("sale", "Venda"),
        ("loss", "Perda"),
        ("internal_use", "Uso interno"),
        ("courtesy", "Cortesia"),
        ("adjustment_positive", "Ajuste positivo"),
        ("adjustment_negative", "Ajuste negativo"),
        ("return_to_stock", "Retorno ao estoque"),
        ("stock_count", "Conferência"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)

    stock_entry = models.ForeignKey(
        StockEntry,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="movements",
    )

    sale_item = models.ForeignKey(
        "sales.SaleItem",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="stock_movements",
    )

    reversal_of = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="reversal",
    )

    movement_type = models.CharField(max_length=30, choices=MOVEMENT_TYPES)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)

    sale_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )

    cost_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )

    reason = models.CharField(max_length=120, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Movimento de estoque"
        verbose_name_plural = "Movimentos de estoque"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=("sale_item", "stock_entry"),
                condition=Q(movement_type="sale"),
                name="uniq_sale_item_stock_entry",
            ),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.get_movement_type_display()} - {self.quantity}"
