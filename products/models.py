from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

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
        result = self.stock_entries.aggregate(total=Sum("remaining_quantity"))
        return result["total"] or Decimal("0.00")

    @property
    def average_cost(self):
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
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="movements",
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

    def find_available_entry(self):
        return (
            StockEntry.objects
            .filter(
                company=self.company,
                product=self.product,
                remaining_quantity__gt=0,
            )
            .order_by("created_at")
            .first()
        )

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        negative_types = [
            "sale",
            "loss",
            "internal_use",
            "courtesy",
            "adjustment_negative",
        ]

        positive_types = [
            "adjustment_positive",
            "return_to_stock",
        ]

        if self.company_id is None and self.product_id is not None:
            self.company = self.product.company

        if self.stock_entry is None and self.movement_type in negative_types:
            self.stock_entry = self.find_available_entry()

        if self.stock_entry is None and self.movement_type in positive_types:
            if self.cost_value is None:
                self.cost_value = self.quantity * self.product.average_cost

            self.stock_entry = StockEntry.objects.create(
                company=self.company,
                product=self.product,
                entry_mode="simple",
                total_cost=self.cost_value,
                quantity_added=self.quantity,
                remaining_quantity=Decimal("0.00"),
                notes=f"Entrada automática por {self.get_movement_type_display()}",
                created_by=self.created_by,
            )

        if self.cost_value is None:
            if self.stock_entry:
                self.cost_value = self.quantity * self.stock_entry.unit_cost
            else:
                self.cost_value = self.quantity * self.product.average_cost

        if self.sale_value is None and self.movement_type == "sale":
            self.sale_value = self.quantity * self.product.sale_price

        super().save(*args, **kwargs)

        if is_new and self.stock_entry and self.movement_type in negative_types:
            self.stock_entry.remaining_quantity -= self.quantity
            self.stock_entry.save(update_fields=["remaining_quantity"])

        if is_new and self.stock_entry and self.movement_type in positive_types:
            self.stock_entry.remaining_quantity += self.quantity
            self.stock_entry.save(update_fields=["remaining_quantity"])

    def __str__(self):
        return f"{self.product.name} - {self.get_movement_type_display()} - {self.quantity}"