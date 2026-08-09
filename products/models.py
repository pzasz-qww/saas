from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum

from companies.models import Company

from .category_names import clean_category_name, normalize_category_name


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


class Category(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="product_categories",
    )
    name = models.CharField(max_length=80)
    normalized_name = models.CharField(max_length=255, editable=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Categoria"
        verbose_name_plural = "Categorias"
        ordering = ("name", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("company", "normalized_name"),
                name="uniq_category_company_norm",
            ),
            models.CheckConstraint(
                condition=~Q(name="") & ~Q(normalized_name=""),
                name="category_names_not_empty",
            ),
        ]
        indexes = [
            models.Index(
                fields=("normalized_name",),
                name="category_norm_idx",
            ),
            models.Index(
                fields=("company", "active", "name"),
                name="category_company_list_idx",
            ),
        ]

    def _prepare_name(self):
        self.name = clean_category_name(self.name)
        self.normalized_name = normalize_category_name(self.name)

        if not self.name or not self.normalized_name:
            raise ValidationError({"name": "Informe um nome de categoria válido."})

        name_max_length = self._meta.get_field("name").max_length
        if len(self.name) > name_max_length:
            raise ValidationError(
                {"name": f"O nome deve ter no máximo {name_max_length} caracteres."}
            )

        normalized_max_length = self._meta.get_field(
            "normalized_name"
        ).max_length
        if len(self.normalized_name) > normalized_max_length:
            raise ValidationError(
                {"name": "O nome informado é muito longo após a normalização."}
            )

    def _validate_company_unchanged(self):
        if self.pk is None:
            return

        category_manager = type(self).objects
        if self._state.db is not None:
            category_manager = category_manager.using(self._state.db)

        original_company_id = (
            category_manager.filter(pk=self.pk)
            .values_list("company_id", flat=True)
            .first()
        )
        if (
            original_company_id is not None
            and self.company_id != original_company_id
        ):
            raise ValidationError(
                {"company": "A empresa de uma categoria existente não pode ser alterada."}
            )

    def full_clean(self, *args, **kwargs):
        self._prepare_name()
        return super().full_clean(*args, **kwargs)

    def clean(self):
        super().clean()
        self._prepare_name()
        self._validate_company_unchanged()

    def save(self, *args, **kwargs):
        self._prepare_name()
        self._validate_company_unchanged()

        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "name" in update_fields:
            kwargs["update_fields"] = set(update_fields) | {"normalized_name"}

        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


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
    category_legacy = models.CharField(max_length=80, blank=True, null=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.RESTRICT,
        blank=True,
        null=True,
        related_name="products",
    )
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

    def clean(self):
        super().clean()
        errors = {}

        valid_product_types = {value for value, _label in self.PRODUCT_TYPES}
        if self.product_type not in valid_product_types:
            errors["product_type"] = "Selecione um tipo de produto válido."

        if self.company_id is not None and self.unit_id is not None:
            unit_company_id = (
                Unit.objects.filter(pk=self.unit_id)
                .values_list("company_id", flat=True)
                .first()
            )
            if (
                unit_company_id is not None
                and unit_company_id != self.company_id
            ):
                errors["unit"] = "Selecione uma unidade da mesma empresa."

        if self.company_id is not None and self.category_id is not None:
            category_company_id = (
                Category.objects.filter(pk=self.category_id)
                .values_list("company_id", flat=True)
                .first()
            )
            if (
                category_company_id is not None
                and category_company_id != self.company_id
            ):
                errors["category"] = "Selecione uma categoria da mesma empresa."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    @property
    def current_stock(self):
        annotated_stock = self._get_annotated_decimal(
            "annotated_current_stock",
            "report_current_stock",
        )

        if annotated_stock is not None:
            return annotated_stock

        result = self.stock_entries.filter(
            company_id=self.company_id
        ).aggregate(total=Sum("remaining_quantity"))
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

        entries = self.stock_entries.filter(
            company_id=self.company_id,
            remaining_quantity__gt=0,
        )

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
        if self.product_id is not None:
            product_company_id = self.product.company_id

            if self.company_id not in (None, product_company_id):
                raise ValidationError(
                    "A entrada e o produto devem pertencer à mesma empresa."
                )

            self.company_id = product_company_id

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

    def clean(self):
        super().clean()
        errors = {}

        invalid_quantity = (
            self.quantity is None
            or not self.quantity.is_finite()
            or self.quantity < 0
            or (self.quantity == 0 and self.movement_type != "stock_count")
        )
        if invalid_quantity:
            errors["quantity"] = "A quantidade do movimento é inválida."

        if self.product_id is not None:
            product_company_id = (
                Product.objects.filter(pk=self.product_id)
                .values_list("company_id", flat=True)
                .first()
            )
            if self.company_id not in (None, product_company_id):
                errors["product"] = "Selecione um produto da mesma empresa."
            elif self.company_id is None:
                self.company_id = product_company_id

        if self.stock_entry_id is not None:
            entry = (
                StockEntry.objects.filter(pk=self.stock_entry_id)
                .values("company_id", "product_id")
                .first()
            )
            if entry and (
                entry["company_id"] != self.company_id
                or entry["product_id"] != self.product_id
            ):
                errors["stock_entry"] = (
                    "A entrada deve pertencer à mesma empresa e ao mesmo produto."
                )

        if self.sale_item_id is not None:
            sale_item_model = self._meta.get_field("sale_item").remote_field.model
            sale_item = (
                sale_item_model.objects.filter(pk=self.sale_item_id)
                .values("company_id", "product_id")
                .first()
            )
            if sale_item and (
                sale_item["company_id"] != self.company_id
                or sale_item["product_id"] != self.product_id
            ):
                errors["sale_item"] = (
                    "O item da venda deve pertencer à mesma empresa e produto."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} - {self.get_movement_type_display()} - {self.quantity}"
