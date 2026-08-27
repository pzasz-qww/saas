from decimal import Decimal

from django import forms
from django.forms import formset_factory

from .models import Product, Unit
from .quantities import (
    QUANTITY_UNIT_CHOICES,
    QuantityConversionError,
    normalize_quantity,
)


AUTOMATIC_PRODUCT_TYPE = "auto"


class CommaDecimalField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip()
            if "," in value and "." not in value and value.count(",") == 1:
                value = value.replace(",", ".")
        return super().to_python(value)


class ProductCreateForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        error_messages={
            "required": "Informe o nome do produto.",
            "max_length": "O nome do produto é muito longo.",
        },
    )
    sale_price = CommaDecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=0,
        error_messages={
            "required": "Informe o preço de venda.",
            "invalid": "Informe um preço de venda válido.",
            "min_value": "O preço de venda não pode ser negativo.",
            "max_digits": "Informe um preço de venda válido.",
            "max_decimal_places": "Use no máximo duas casas decimais no preço.",
        },
    )
    sale_form = forms.ChoiceField(
        choices=Product.SALE_FORMS,
        required=False,
        error_messages={"invalid_choice": "Selecione uma forma de venda válida."},
    )

    category = forms.CharField(max_length=80, required=False)
    product_type = forms.ChoiceField(
        choices=(
            (AUTOMATIC_PRODUCT_TYPE, "Automático conforme o papel"),
            *Product.PRODUCT_TYPES,
        ),
        required=False,
    )
    unit = forms.ModelChoiceField(queryset=Unit.objects.none(), required=False)
    inventory_role = forms.ChoiceField(
        choices=Product.INVENTORY_ROLES,
        required=False,
    )
    stock_dimension = forms.ChoiceField(
        choices=Product.STOCK_DIMENSIONS,
        required=False,
    )
    unit_description = forms.CharField(max_length=120, required=False)
    dose_ml = CommaDecimalField(
        max_digits=20,
        decimal_places=6,
        required=False,
        error_messages={
            "invalid": "Informe um volume de dose válido.",
            "max_digits": "Informe um volume de dose válido.",
            "max_decimal_places": "Use no máximo seis casas decimais.",
        },
    )
    portion_g = CommaDecimalField(
        max_digits=20,
        decimal_places=6,
        required=False,
        error_messages={
            "invalid": "Informe um peso de porção válido.",
            "max_digits": "Informe um peso de porção válido.",
            "max_decimal_places": "Use no máximo seis casas decimais.",
        },
    )
    preparation_mode = forms.ChoiceField(
        choices=(
            ("", "Selecione"),
            ("on_demand", "Feito na hora"),
            ("pre_portioned", "Exige porcionamento prévio"),
        ),
        required=False,
    )
    minimum_quantity = CommaDecimalField(
        max_digits=20,
        decimal_places=6,
        min_value=0,
        required=False,
        error_messages={
            "invalid": "Informe um estoque mínimo válido.",
            "min_value": "O estoque mínimo não pode ser negativo.",
            "max_digits": "Informe um estoque mínimo válido.",
            "max_decimal_places": "Use no máximo seis casas decimais.",
        },
    )
    active = forms.BooleanField(required=False)

    def __init__(self, *args, company, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)
        self.fields["unit"].queryset = Unit.objects.filter(
            company=company,
        ).order_by("name", "id")
        self.fields["unit"].empty_label = "Automática (recomendado)"
        self.fields["active"].initial = True

        for field_name, field in self.fields.items():
            field.widget.attrs["id"] = field_name

        widget_attributes = {
            "name": {"placeholder": "Ex: Porção de batata", "autocomplete": "off"},
            "sale_price": {"placeholder": "Ex: 28,00", "inputmode": "decimal"},
            "category": {"placeholder": "Ex: Bebidas, Porções"},
            "unit_description": {
                "placeholder": "Ex: garrafa 600 ml, lata 350 ml, pacote"
            },
            "dose_ml": {"placeholder": "Ex: 50", "inputmode": "decimal"},
            "portion_g": {"placeholder": "Ex: 500", "inputmode": "decimal"},
            "minimum_quantity": {"placeholder": "Ex: 5", "inputmode": "decimal"},
        }
        for field_name, attributes in widget_attributes.items():
            self.fields[field_name].widget.attrs.update(attributes)

    def _choice_with_default(self, field_name, default):
        raw_value = self.data.get(field_name) if self.is_bound else None
        if raw_value in (None, ""):
            return default
        return self.cleaned_data.get(field_name)

    def clean_sale_form(self):
        return self._choice_with_default("sale_form", "unit")

    def clean_inventory_role(self):
        return self._choice_with_default("inventory_role", "direct")

    def clean_stock_dimension(self):
        return self._choice_with_default("stock_dimension", "count")

    def clean_product_type(self):
        raw_value = self.data.get("product_type") if self.is_bound else None
        if raw_value in (None, AUTOMATIC_PRODUCT_TYPE):
            return None
        if raw_value == "":
            raise forms.ValidationError("Selecione um tipo de produto válido.")
        return self.cleaned_data.get("product_type")

    def clean_active(self):
        if self.is_bound and "active_present" not in self.data and "active" not in self.data:
            return True
        return self.cleaned_data.get("active", False)

    def clean(self):
        cleaned_data = super().clean()
        inventory_role = cleaned_data.get("inventory_role")
        preparation_mode = cleaned_data.get("preparation_mode") or None

        if inventory_role == "prepared" and preparation_mode is None:
            self.add_error(
                "preparation_mode",
                "Selecione o modo de preparo do produto preparado.",
            )
        elif inventory_role and inventory_role != "prepared":
            preparation_mode = None

        for field_name, label in (
            ("dose_ml", "O volume da dose"),
            ("portion_g", "O peso da porção"),
        ):
            value = cleaned_data.get(field_name)
            if value is not None and value <= 0:
                self.add_error(field_name, f"{label} deve ser positivo.")

        if cleaned_data.get("minimum_quantity") is None:
            cleaned_data["minimum_quantity"] = Decimal("0")

        if cleaned_data.get("product_type") is None and inventory_role:
            cleaned_data["product_type"] = (
                "internal_use" if inventory_role == "input" else "sale"
            )

        cleaned_data["preparation_mode"] = preparation_mode
        return cleaned_data


class ProductComponentForm(forms.Form):
    ingredient = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        error_messages={
            "required": "Selecione o ingrediente.",
            "invalid_choice": "Selecione um ingrediente válido.",
        },
    )
    quantity = CommaDecimalField(
        max_digits=20,
        decimal_places=6,
        error_messages={
            "required": "Informe a quantidade deste ingrediente.",
            "invalid": "Informe uma quantidade válida para este ingrediente.",
            "max_digits": "Informe uma quantidade válida para este ingrediente.",
            "max_decimal_places": "Use no máximo seis casas decimais.",
        },
    )
    unit = forms.ChoiceField(
        choices=(("", "Selecione"), *QUANTITY_UNIT_CHOICES),
        error_messages={
            "required": "Selecione a unidade deste ingrediente.",
            "invalid_choice": "Selecione uma unidade válida.",
        },
    )

    def __init__(self, *args, company, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)
        self.fields["ingredient"].queryset = (
            Product.objects.filter(company=company)
            .exclude(inventory_role="prepared")
            .select_related("unit")
            .order_by("inventory_role", "name", "id")
        )
        self.fields["quantity"].widget.attrs.update(
            {"inputmode": "decimal", "placeholder": "Ex: 50"}
        )

    def has_changed(self):
        if self.is_bound:
            ingredient = self.data.get(self.add_prefix("ingredient"), "")
            quantity = self.data.get(self.add_prefix("quantity"), "")
            if not str(ingredient).strip() and not str(quantity).strip():
                return False

        return super().has_changed()

    def clean(self):
        cleaned_data = super().clean()
        ingredient = cleaned_data.get("ingredient")
        quantity = cleaned_data.get("quantity")
        unit = cleaned_data.get("unit")

        if ingredient is None or quantity is None or not unit:
            return cleaned_data

        if ingredient.inventory_role == "prepared":
            self.add_error(
                "ingredient",
                "Produtos preparados não podem ser usados como ingredientes.",
            )
            return cleaned_data

        try:
            normalized = normalize_quantity(quantity, unit)
        except QuantityConversionError as error:
            self.add_error("quantity", str(error))
            return cleaned_data

        if normalized.dimension != ingredient.stock_dimension:
            self.add_error(
                "unit",
                "A unidade é incompatível com a dimensão de estoque do ingrediente.",
            )

        return cleaned_data


ProductComponentFormSet = formset_factory(
    ProductComponentForm,
    extra=1,
    can_delete=True,
)


__all__ = [
    "ProductComponentForm",
    "ProductComponentFormSet",
    "ProductCreateForm",
]
