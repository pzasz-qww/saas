from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone

from companies.models import Company

from .category_names import clean_category_name, normalize_category_name
from .money import InvalidMoneyValue, decimal_amount
from .quantities import (
    QUANTITY_UNIT_CHOICES,
    QuantityConversionError,
    base_unit_for_dimension,
    normalize_quantity,
)


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
    INVENTORY_ROLES = [
        ("direct", "Venda direta"),
        ("input", "Insumo"),
        ("prepared", "Preparado"),
    ]
    SALE_FORMS = [
        ("unit", "Unidade"),
        ("dose", "Dose"),
        ("portion", "Porção"),
    ]
    STOCK_DIMENSIONS = [
        ("count", "Contagem"),
        ("weight", "Peso"),
        ("volume", "Volume"),
    ]
    PREPARATION_MODES = [
        ("on_demand", "Sob demanda"),
        ("pre_portioned", "Pré-porcionado"),
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

    inventory_role = models.CharField(
        max_length=20,
        choices=INVENTORY_ROLES,
        default="direct",
    )
    sale_form = models.CharField(
        max_length=20,
        choices=SALE_FORMS,
        default="unit",
    )
    stock_dimension = models.CharField(
        max_length=20,
        choices=STOCK_DIMENSIONS,
        default="count",
    )
    unit_description = models.CharField(max_length=120, blank=True, default="")
    dose_ml = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        blank=True,
        null=True,
    )
    portion_g = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        blank=True,
        null=True,
    )
    preparation_mode = models.CharField(
        max_length=20,
        choices=PREPARATION_MODES,
        blank=True,
        null=True,
    )

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)

    sale_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Preço cobrado por unidade vendida. Exemplo: R$ 28 por porção.",
    )

    active = models.BooleanField(default=True)

    minimum_quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        default=0,
        help_text="Quantidade mínima para alerta de estoque baixo.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Produto"
        verbose_name_plural = "Produtos"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(dose_ml__isnull=True) | Q(dose_ml__gt=0),
                name="product_dose_ml_positive",
            ),
            models.CheckConstraint(
                condition=Q(portion_g__isnull=True) | Q(portion_g__gt=0),
                name="product_portion_g_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        inventory_role="prepared",
                        preparation_mode__in=("on_demand", "pre_portioned"),
                    )
                    | (
                        ~Q(inventory_role="prepared")
                        & Q(preparation_mode__isnull=True)
                    )
                ),
                name="product_preparation_mode_domain",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        valid_product_types = {value for value, _label in self.PRODUCT_TYPES}
        if self.product_type not in valid_product_types:
            errors["product_type"] = "Selecione um tipo de produto válido."

        choice_fields = (
            ("inventory_role", self.INVENTORY_ROLES, "papel do produto"),
            ("sale_form", self.SALE_FORMS, "forma de venda"),
            ("stock_dimension", self.STOCK_DIMENSIONS, "dimensão de estoque"),
        )
        for field_name, choices, label in choice_fields:
            valid_values = {value for value, _label in choices}
            if getattr(self, field_name) not in valid_values:
                errors[field_name] = f"Selecione um(a) {label} válido(a)."

        valid_preparation_modes = {
            value for value, _label in self.PREPARATION_MODES
        }
        if self.preparation_mode == "":
            self.preparation_mode = None

        if self.inventory_role == "prepared":
            if self.preparation_mode not in valid_preparation_modes:
                errors["preparation_mode"] = (
                    "Selecione como o produto preparado afeta o estoque."
                )
        elif self.preparation_mode not in (None, ""):
            errors["preparation_mode"] = (
                "O modo de preparo só se aplica a produtos preparados."
            )

        for field_name, label in (
            ("dose_ml", "O volume da dose"),
            ("portion_g", "O peso da porção"),
        ):
            value = getattr(self, field_name)
            if value is None:
                continue

            try:
                value = value if isinstance(value, Decimal) else Decimal(str(value))
            except (ArithmeticError, TypeError, ValueError):
                errors[field_name] = f"{label} deve ser um número válido."
                continue

            if not value.is_finite() or value <= 0:
                errors[field_name] = f"{label} deve ser positivo."
            else:
                setattr(self, field_name, value)

        if self.sale_form == "dose":
            if self.stock_dimension != "volume":
                errors["stock_dimension"] = (
                    "Produtos vendidos por dose precisam controlar estoque por volume."
                )
            if self.dose_ml is None:
                errors["dose_ml"] = "Informe o volume de cada dose em mL."

        if self.sale_form == "portion":
            if self.stock_dimension != "weight":
                errors["stock_dimension"] = (
                    "Produtos vendidos por porção precisam controlar estoque por peso."
                )
            if self.portion_g is None:
                errors["portion_g"] = "Informe o peso de cada porção em gramas."

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

    @property
    def stock_base_unit(self):
        return base_unit_for_dimension(self.stock_dimension) or "unit"

    @property
    def stock_base_unit_label(self):
        return dict(QUANTITY_UNIT_CHOICES).get(
            self.stock_base_unit,
            self.stock_base_unit,
        )

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


class ProductComponent(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="product_components",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="components",
    )
    ingredient = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="used_in_components",
    )
    quantity = models.DecimalField(max_digits=20, decimal_places=6)
    unit = models.CharField(max_length=10, choices=QUANTITY_UNIT_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Componente do produto"
        verbose_name_plural = "Componentes dos produtos"
        ordering = ("product_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("product", "ingredient"),
                name="uniq_product_component_ingredient",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name="product_component_quantity_positive",
            ),
            models.CheckConstraint(
                condition=~Q(product=F("ingredient")),
                name="product_component_not_self",
            ),
        ]
        indexes = [
            models.Index(
                fields=("company", "product"),
                name="component_company_product_idx",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        product_data = None
        if self.product_id is not None:
            product_data = (
                Product.objects.filter(pk=self.product_id)
                .values("company_id", "inventory_role")
                .first()
            )

        ingredient_data = None
        if self.ingredient_id is not None:
            ingredient_data = (
                Product.objects.filter(pk=self.ingredient_id)
                .values(
                    "company_id",
                    "inventory_role",
                    "stock_dimension",
                    "active",
                )
                .first()
            )

        if self.product_id is not None and self.product_id == self.ingredient_id:
            errors["ingredient"] = "O produto não pode ser ingrediente de si mesmo."

        if product_data is not None:
            if self.company_id is None:
                self.company_id = product_data["company_id"]
            elif self.company_id != product_data["company_id"]:
                errors["product"] = "O produto deve pertencer à mesma empresa."

            if product_data["inventory_role"] != "prepared":
                errors["product"] = (
                    "Somente produtos preparados podem possuir composição."
                )

        if ingredient_data is not None:
            expected_company_id = (
                product_data["company_id"] if product_data is not None else self.company_id
            )
            if ingredient_data["company_id"] != expected_company_id:
                errors["ingredient"] = (
                    "O ingrediente deve pertencer à mesma empresa do produto."
                )
            elif ingredient_data["inventory_role"] == "prepared":
                errors["ingredient"] = (
                    "Produtos preparados não podem ser usados como ingredientes."
                )
            elif not ingredient_data["active"]:
                errors["ingredient"] = "O ingrediente precisa estar ativo."

        normalized = None
        if self.quantity is not None and self.unit:
            try:
                normalized = normalize_quantity(self.quantity, self.unit)
            except QuantityConversionError as error:
                errors["quantity"] = str(error)

        if normalized is not None and ingredient_data is not None:
            if normalized.dimension != ingredient_data["stock_dimension"]:
                errors["unit"] = (
                    "A unidade informada é incompatível com a dimensão de estoque "
                    "do ingrediente."
                )
            else:
                physical_quantum = Decimal("0.000001")
                normalized_quantity = normalized.quantity.quantize(
                    physical_quantum
                )
                if normalized_quantity != normalized.quantity:
                    errors["quantity"] = (
                        "A quantidade normalizada excede seis casas decimais."
                    )
                else:
                    self.quantity = normalized_quantity
                    self.unit = normalized.base_unit

        if self.pk is not None:
            original = (
                type(self).objects.filter(pk=self.pk)
                .values("company_id", "product_id")
                .first()
            )
            if original is not None:
                if original["company_id"] != self.company_id:
                    errors["company"] = (
                        "A empresa de uma composição existente não pode ser alterada."
                    )
                if original["product_id"] != self.product_id:
                    errors["product"] = (
                        "O produto de uma composição existente não pode ser alterado."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if isinstance(self.quantity, float):
            raise ValidationError(
                {"quantity": "A quantidade deve ser informada sem usar float."}
            )

        with transaction.atomic():
            if self.product_id is not None:
                product = Product.objects.select_for_update().get(
                    pk=self.product_id
                )
                if self.company_id is None:
                    self.company_id = product.company_id

            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            Product.objects.select_for_update().get(pk=self.product_id)
            return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.product}: {self.ingredient} ({self.quantity} {self.unit})"


class Production(models.Model):
    STATUS_COMPLETED = "completed"
    STATUS_REVERSED = "reversed"
    STATUS_CHOICES = (
        (STATUS_COMPLETED, "Concluída"),
        (STATUS_REVERSED, "Revertida"),
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="productions",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="productions",
    )
    planned_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    produced_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    production_date = models.DateField(default=timezone.localdate)
    expiration_date = models.DateField(blank=True, null=True)
    total_cost = models.DecimalField(max_digits=20, decimal_places=10)
    notes = models.TextField(blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_COMPLETED,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="productions_created",
    )
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="productions_reversed",
    )
    reversed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Produção"
        verbose_name_plural = "Produções"
        ordering = ("-production_date", "-id")
        constraints = [
            models.CheckConstraint(
                condition=Q(planned_quantity__gt=0),
                name="production_planned_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(produced_quantity__gt=0),
                name="production_produced_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(total_cost__gte=0),
                name="production_total_cost_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=("company", "product", "status"),
                name="production_company_product_idx",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        product_data = None
        if self.product_id is not None:
            product_data = (
                Product.objects.filter(pk=self.product_id)
                .values("company_id", "inventory_role", "preparation_mode")
                .first()
            )
        if product_data is not None:
            if self.company_id is None:
                self.company_id = product_data["company_id"]
            elif self.company_id != product_data["company_id"]:
                errors["product"] = "O produto pertence a outra empresa."
            if self._state.adding and not (
                product_data["inventory_role"] == "prepared"
                and product_data["preparation_mode"] == "pre_portioned"
            ):
                errors["product"] = (
                    "Somente produtos preparados antecipadamente podem ser produzidos."
                )

        for field_name, label in (
            ("planned_quantity", "A quantidade planejada"),
            ("produced_quantity", "A quantidade produzida"),
        ):
            value = getattr(self, field_name)
            if isinstance(value, float) or not isinstance(value, Decimal):
                errors[field_name] = f"{label} é inválida."
            elif not value.is_finite() or value <= 0:
                errors[field_name] = f"{label} deve ser positiva."

        if isinstance(self.total_cost, float) or not isinstance(
            self.total_cost,
            Decimal,
        ):
            errors["total_cost"] = "O custo total é inválido."
        elif not self.total_cost.is_finite() or self.total_cost < 0:
            errors["total_cost"] = "O custo total não pode ser negativo."

        if (
            self.production_date
            and self.expiration_date
            and self.expiration_date < self.production_date
        ):
            errors["expiration_date"] = (
                "A validade não pode ser anterior à data da produção."
            )

        if self.status == self.STATUS_COMPLETED:
            if self.reversed_at is not None or self.reversed_by_id is not None:
                errors["status"] = (
                    "Uma produção concluída não pode possuir dados de reversão."
                )
        elif self.status == self.STATUS_REVERSED and self.reversed_at is None:
            errors["reversed_at"] = "Informe quando a produção foi revertida."

        if self.pk is not None:
            original = (
                type(self).objects.filter(pk=self.pk)
                .values_list(
                    "company_id",
                    "product_id",
                    "planned_quantity",
                    "produced_quantity",
                    "production_date",
                    "expiration_date",
                    "total_cost",
                    "notes",
                    "created_by_id",
                )
                .first()
            )
            current = (
                self.company_id,
                self.product_id,
                self.planned_quantity,
                self.produced_quantity,
                self.production_date,
                self.expiration_date,
                self.total_cost,
                self.notes,
                self.created_by_id,
            )
            if original is not None and original != current:
                errors["product"] = (
                    "Os dados históricos de uma produção não podem ser alterados."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def theoretical_yield(self):
        return self.planned_quantity

    @property
    def actual_yield(self):
        return self.produced_quantity

    @property
    def yield_percentage(self):
        if not self.planned_quantity:
            return Decimal("0")
        return self.produced_quantity * Decimal("100") / self.planned_quantity

    @property
    def yield_difference(self):
        return self.planned_quantity - self.produced_quantity

    @property
    def unit_cost(self):
        if not self.produced_quantity:
            return Decimal("0")
        return self.total_cost / self.produced_quantity

    def __str__(self):
        return f"Produção #{self.pk} — {self.product.name}"


class ProductionConsumption(models.Model):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="production_consumptions",
    )
    production = models.ForeignKey(
        Production,
        on_delete=models.PROTECT,
        related_name="consumptions",
    )
    source_component = models.ForeignKey(
        ProductComponent,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="production_snapshots",
    )
    ingredient = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="production_consumptions",
    )
    quantity_per_planned_unit = models.DecimalField(
        max_digits=20,
        decimal_places=6,
    )
    theoretical_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    actual_quantity = models.DecimalField(max_digits=20, decimal_places=6)
    loss_quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        default=0,
    )
    base_unit = models.CharField(max_length=10, choices=QUANTITY_UNIT_CHOICES)
    total_cost = models.DecimalField(max_digits=20, decimal_places=10)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Consumo da produção"
        verbose_name_plural = "Consumos das produções"
        ordering = ("production_id", "ingredient_id", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("production", "ingredient"),
                name="uniq_production_ingredient",
            ),
            models.CheckConstraint(
                condition=Q(quantity_per_planned_unit__gt=0),
                name="prodcons_quantity_per_unit_positive",
            ),
            models.CheckConstraint(
                condition=Q(theoretical_quantity__gt=0),
                name="prodcons_theoretical_positive",
            ),
            models.CheckConstraint(
                condition=Q(actual_quantity__gt=0),
                name="prodcons_actual_positive",
            ),
            models.CheckConstraint(
                condition=Q(loss_quantity__gte=0),
                name="prodcons_loss_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(loss_quantity__lte=F("actual_quantity")),
                name="prodcons_loss_not_above_actual",
            ),
            models.CheckConstraint(
                condition=Q(total_cost__gte=0),
                name="prodcons_cost_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=("company", "production"),
                name="prodcons_company_prod_idx",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        production_data = None
        if self.production_id is not None:
            production_data = (
                Production.objects.filter(pk=self.production_id)
                .values("company_id", "product_id", "planned_quantity")
                .first()
            )
        ingredient_data = None
        if self.ingredient_id is not None:
            ingredient_data = (
                Product.objects.filter(pk=self.ingredient_id)
                .values("company_id", "stock_dimension")
                .first()
            )

        if production_data is not None:
            if self.company_id is None:
                self.company_id = production_data["company_id"]
            elif self.company_id != production_data["company_id"]:
                errors["production"] = "A produção pertence a outra empresa."

        if ingredient_data is not None:
            if ingredient_data["company_id"] != self.company_id:
                errors["ingredient"] = "O ingrediente pertence a outra empresa."
            expected_unit = base_unit_for_dimension(
                ingredient_data["stock_dimension"]
            )
            if self.base_unit != expected_unit:
                errors["base_unit"] = (
                    "A unidade física não corresponde ao estoque do ingrediente."
                )

        decimal_fields = (
            "quantity_per_planned_unit",
            "theoretical_quantity",
            "actual_quantity",
            "loss_quantity",
            "total_cost",
        )
        for field_name in decimal_fields:
            value = getattr(self, field_name)
            if isinstance(value, float) or not isinstance(value, Decimal):
                errors[field_name] = "Informe um valor decimal válido."
            elif not value.is_finite():
                errors[field_name] = "Informe um valor decimal finito."

        if isinstance(self.quantity_per_planned_unit, Decimal) and (
            self.quantity_per_planned_unit <= 0
        ):
            errors["quantity_per_planned_unit"] = "A quantidade deve ser positiva."
        if isinstance(self.theoretical_quantity, Decimal) and (
            self.theoretical_quantity <= 0
        ):
            errors["theoretical_quantity"] = "A quantidade deve ser positiva."
        if isinstance(self.actual_quantity, Decimal) and self.actual_quantity <= 0:
            errors["actual_quantity"] = "A quantidade deve ser positiva."
        if isinstance(self.loss_quantity, Decimal) and self.loss_quantity < 0:
            errors["loss_quantity"] = "A perda não pode ser negativa."
        if (
            isinstance(self.loss_quantity, Decimal)
            and isinstance(self.actual_quantity, Decimal)
            and self.loss_quantity > self.actual_quantity
        ):
            errors["loss_quantity"] = "A perda não pode superar o consumo real."
        if isinstance(self.total_cost, Decimal) and self.total_cost < 0:
            errors["total_cost"] = "O custo não pode ser negativo."

        if (
            production_data is not None
            and isinstance(self.quantity_per_planned_unit, Decimal)
            and isinstance(self.theoretical_quantity, Decimal)
            and self.theoretical_quantity
            != production_data["planned_quantity"]
            * self.quantity_per_planned_unit
        ):
            errors["theoretical_quantity"] = (
                "A necessidade teórica não corresponde ao planejamento."
            )

        if self.source_component_id is not None and production_data is not None:
            source_data = (
                ProductComponent.objects.filter(pk=self.source_component_id)
                .values("company_id", "product_id", "ingredient_id")
                .first()
            )
            if source_data and (
                source_data["company_id"] != self.company_id
                or source_data["product_id"] != production_data["product_id"]
                or source_data["ingredient_id"] != self.ingredient_id
            ):
                errors["source_component"] = (
                    "O componente de origem não corresponde ao consumo."
                )

        if self.pk is not None:
            original = (
                type(self).objects.filter(pk=self.pk)
                .values_list(
                    "company_id",
                    "production_id",
                    "source_component_id",
                    "ingredient_id",
                    "quantity_per_planned_unit",
                    "theoretical_quantity",
                    "actual_quantity",
                    "loss_quantity",
                    "base_unit",
                    "total_cost",
                )
                .first()
            )
            current = (
                self.company_id,
                self.production_id,
                self.source_component_id,
                self.ingredient_id,
                self.quantity_per_planned_unit,
                self.theoretical_quantity,
                self.actual_quantity,
                self.loss_quantity,
                self.base_unit,
                self.total_cost,
            )
            if original is not None and original != current:
                errors["production"] = (
                    "O consumo histórico de uma produção não pode ser alterado."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.production}: {self.ingredient.name} "
            f"({self.actual_quantity} {self.base_unit})"
        )


class StockEntry(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_entries",
    )

    production = models.OneToOneField(
        Production,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="output_stock_entry",
    )

    input_quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        default=0,
        help_text="Quantidade originalmente informada pelo usu\u00e1rio.",
    )

    input_unit = models.CharField(
        max_length=10,
        choices=QUANTITY_UNIT_CHOICES,
        default="",
        help_text="Unidade originalmente informada pelo usu\u00e1rio.",
    )

    total_cost = models.DecimalField(
        max_digits=20,
        decimal_places=10,
        default=0,
        help_text="Valor total investido. Exemplo: R$ 150 em batata.",
    )

    quantity_added = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        help_text="Quantidade gerada. Exemplo: 30 porções ou 24 unidades.",
    )

    base_unit = models.CharField(
        max_length=10,
        choices=QUANTITY_UNIT_CHOICES,
        default="",
        help_text="Unidade-base da quantidade oficial do lote.",
    )

    remaining_quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
    )

    notes = models.TextField(blank=True, null=True)

    entry_date = models.DateField(default=timezone.localdate)

    expiration_date = models.DateField(blank=True, null=True)

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
        constraints = [
            models.CheckConstraint(
                condition=Q(input_quantity__gt=0),
                name="stock_entry_input_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(quantity_added__gt=0),
                name="stock_entry_normalized_quantity_positive",
            ),
            models.CheckConstraint(
                condition=Q(remaining_quantity__gte=0),
                name="stock_entry_remaining_quantity_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(remaining_quantity__lte=F("quantity_added")),
                name="stock_entry_remaining_not_above_initial",
            ),
            models.CheckConstraint(
                condition=Q(total_cost__gte=0),
                name="stock_entry_total_cost_nonnegative",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.product_id is not None:
            product_company_id = self.product.company_id
            if self.company_id not in (None, product_company_id):
                errors["company"] = (
                    "A entrada e o produto devem pertencer \u00e0 mesma empresa."
                )
            self.company_id = product_company_id

            if self.input_quantity in (None, Decimal("0")):
                self.input_quantity = self.quantity_added
            if not self.input_unit:
                self.input_unit = base_unit_for_dimension(
                    self.product.stock_dimension
                )

        if self.production_id is not None:
            production_data = (
                Production.objects.filter(pk=self.production_id)
                .values("company_id", "product_id", "production_date", "expiration_date")
                .first()
            )
            if production_data and (
                production_data["company_id"] != self.company_id
                or production_data["product_id"] != self.product_id
            ):
                errors["production"] = (
                    "O lote produzido não corresponde à empresa e ao produto."
                )
            elif production_data and (
                self.entry_date != production_data["production_date"]
                or self.expiration_date != production_data["expiration_date"]
            ):
                errors["production"] = (
                    "As datas do lote precisam corresponder à produção."
                )

        if self.pk is not None:
            original = (
                type(self).objects.filter(pk=self.pk)
                .values_list(
                    "company_id",
                    "product_id",
                    "production_id",
                    "input_quantity",
                    "input_unit",
                    "total_cost",
                    "quantity_added",
                    "base_unit",
                    "notes",
                    "entry_date",
                    "expiration_date",
                    "created_by_id",
                )
                .first()
            )
            current = (
                self.company_id,
                self.product_id,
                self.production_id,
                self.input_quantity,
                self.input_unit,
                self.total_cost,
                self.quantity_added,
                self.base_unit,
                self.notes,
                self.entry_date,
                self.expiration_date,
                self.created_by_id,
            )
            if (
                original is not None
                and (original[2] is not None or self.production_id is not None)
                and original != current
            ):
                errors["production"] = (
                    "Os dados de origem de um lote produzido não podem ser alterados."
                )

        try:
            normalized = normalize_quantity(self.input_quantity, self.input_unit)
        except QuantityConversionError as error:
            errors["input_quantity"] = str(error)
            normalized = None

        if normalized is not None and self.product_id is not None:
            if normalized.dimension != self.product.stock_dimension:
                errors["input_unit"] = (
                    "A unidade informada \u00e9 incompat\u00edvel com a dimens\u00e3o "
                    "de estoque deste produto."
                )
            else:
                self.quantity_added = normalized.quantity
                self.base_unit = normalized.base_unit

        try:
            self.total_cost = decimal_amount(self.total_cost)
        except InvalidMoneyValue as error:
            errors["total_cost"] = str(error)
        else:
            if self.total_cost < 0:
                errors["total_cost"] = "O custo total n\u00e3o pode ser negativo."

        if self.remaining_quantity is None and normalized is not None:
            self.remaining_quantity = normalized.quantity

        if self.remaining_quantity is not None:
            try:
                remaining = decimal_amount(self.remaining_quantity)
            except InvalidMoneyValue:
                errors["remaining_quantity"] = "O saldo do lote \u00e9 inv\u00e1lido."
            else:
                if remaining < 0:
                    errors["remaining_quantity"] = (
                        "O saldo do lote n\u00e3o pode ser negativo."
                    )
                elif normalized is not None and remaining > normalized.quantity:
                    errors["remaining_quantity"] = (
                        "O saldo do lote n\u00e3o pode superar a quantidade inicial."
                    )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.product_id is not None:
            fallback_unit = base_unit_for_dimension(self.product.stock_dimension)
            if self.input_quantity in (None, Decimal("0")):
                self.input_quantity = self.quantity_added
            if not self.input_unit:
                self.input_unit = fallback_unit
            if not self.base_unit:
                self.base_unit = fallback_unit
        if self.remaining_quantity is None:
            self.remaining_quantity = self.quantity_added

        self.full_clean()
        if self.product_id is not None:
            product_company_id = self.product.company_id

            if self.company_id not in (None, product_company_id):
                raise ValidationError(
                    "A entrada e o produto devem pertencer à mesma empresa."
                )

            self.company_id = product_company_id

        super().save(*args, **kwargs)

    @property
    def normalized_quantity(self):
        return self.quantity_added

    @property
    def normalized_unit_cost(self):
        if not self.quantity_added:
            return Decimal("0.00")

        return self.total_cost / self.quantity_added

    @property
    def unit_cost(self):
        return self.normalized_unit_cost

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
        ("production_consumption", "Consumo em produção"),
        ("production_output", "Entrada por produção"),
        ("production_return", "Retorno de produção"),
        ("production_output_reversal", "Reversão do lote produzido"),
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

    sale_item_component = models.ForeignKey(
        "sales.SaleItemComponent",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="stock_movements",
    )

    production = models.ForeignKey(
        Production,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="stock_movements",
    )

    production_consumption = models.ForeignKey(
        ProductionConsumption,
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
    quantity = models.DecimalField(max_digits=20, decimal_places=6)

    sale_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
    )

    cost_value = models.DecimalField(
        max_digits=20,
        decimal_places=10,
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
            models.CheckConstraint(
                condition=(
                    Q(sale_item_component__isnull=True)
                    | Q(sale_item__isnull=False)
                ),
                name="movement_component_requires_sale_item",
            ),
            models.CheckConstraint(
                condition=(
                    Q(production_consumption__isnull=True)
                    | Q(production__isnull=False)
                ),
                name="movement_consumption_requires_prod",
            ),
            models.CheckConstraint(
                condition=(
                    Q(production__isnull=True)
                    | Q(sale_item__isnull=True)
                ),
                name="movement_sale_or_production",
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

        sale_item_data = None
        if self.sale_item_id is not None:
            sale_item_model = self._meta.get_field("sale_item").remote_field.model
            sale_item_data = (
                sale_item_model.objects.filter(pk=self.sale_item_id)
                .values("company_id", "product_id")
                .first()
            )

        component_data = None
        if self.sale_item_component_id is not None:
            component_model = self._meta.get_field(
                "sale_item_component"
            ).remote_field.model
            component_data = (
                component_model.objects.filter(pk=self.sale_item_component_id)
                .values("company_id", "sale_item_id", "ingredient_id")
                .first()
            )
            if self.sale_item_id is None:
                errors["sale_item"] = (
                    "Um movimento de componente precisa de um item da venda."
                )
            elif component_data and (
                component_data["company_id"] != self.company_id
                or component_data["sale_item_id"] != self.sale_item_id
                or component_data["ingredient_id"] != self.product_id
            ):
                errors["sale_item_component"] = (
                    "O componente da venda não corresponde ao movimento."
                )
        elif sale_item_data and (
            sale_item_data["company_id"] != self.company_id
            or sale_item_data["product_id"] != self.product_id
        ):
            errors["sale_item"] = (
                "O item da venda deve pertencer à mesma empresa e produto."
            )

        if sale_item_data and sale_item_data["company_id"] != self.company_id:
            if "sale_item" not in errors:
                errors["sale_item"] = (
                    "O item da venda deve pertencer à mesma empresa."
                )

        production_data = None
        if self.production_id is not None:
            production_data = (
                Production.objects.filter(pk=self.production_id)
                .values("company_id", "product_id")
                .first()
            )
            if self.sale_item_id is not None:
                errors["production"] = (
                    "Um movimento não pode pertencer a venda e produção ao mesmo tempo."
                )
            if production_data and production_data["company_id"] != self.company_id:
                errors["production"] = "A produção pertence a outra empresa."

        if self.production_consumption_id is not None:
            consumption_data = (
                ProductionConsumption.objects.filter(
                    pk=self.production_consumption_id
                )
                .values("company_id", "production_id", "ingredient_id")
                .first()
            )
            if self.production_id is None:
                errors["production"] = (
                    "O consumo precisa estar ligado à produção."
                )
            elif consumption_data and (
                consumption_data["company_id"] != self.company_id
                or consumption_data["production_id"] != self.production_id
                or consumption_data["ingredient_id"] != self.product_id
            ):
                errors["production_consumption"] = (
                    "O consumo da produção não corresponde ao movimento."
                )
        elif production_data and self.movement_type in {
            "production_output",
            "production_output_reversal",
        } and production_data["product_id"] != self.product_id:
            errors["production"] = (
                "O lote produzido deve pertencer ao produto da produção."
            )

        production_types = {
            "production_consumption",
            "production_output",
            "production_return",
            "production_output_reversal",
        }
        component_types = {
            "production_consumption",
            "production_return",
        }
        reversal_types = {
            "production_return",
            "production_output_reversal",
        }
        if self.movement_type in production_types and self.production_id is None:
            errors["production"] = "O movimento precisa estar ligado à produção."
        if self.movement_type not in production_types and self.production_id is not None:
            errors["production"] = (
                "Somente movimentos de produção podem estar ligados a uma produção."
            )
        if (
            self.movement_type in component_types
            and self.production_consumption_id is None
        ):
            errors["production_consumption"] = (
                "O movimento precisa identificar o consumo da produção."
            )
        if (
            self.movement_type in production_types - component_types
            and self.production_consumption_id is not None
        ):
            errors["production_consumption"] = (
                "O movimento do lote produzido não pode apontar para um ingrediente."
            )
        if self.movement_type in reversal_types and self.reversal_of_id is None:
            errors["reversal_of"] = "O movimento de reversão precisa indicar sua origem."
        if (
            self.movement_type in production_types - reversal_types
            and self.reversal_of_id is not None
        ):
            errors["reversal_of"] = (
                "O movimento original da produção não pode ser uma reversão."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product.name} - {self.get_movement_type_display()} - {self.quantity}"
