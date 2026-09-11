from decimal import Decimal

from django import forms
from django.forms import formset_factory
from django.utils import timezone

from .models import Product, Unit
from .quantities import (
    QUANTITY_UNIT_CHOICES,
    QuantityConversionError,
    normalize_quantity,
    units_for_dimension,
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
        sale_form = cleaned_data.get("sale_form")
        stock_dimension = cleaned_data.get("stock_dimension")

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

        if sale_form == "dose":
            if stock_dimension != "volume":
                self.add_error(
                    "stock_dimension",
                    "Produtos vendidos por dose precisam controlar estoque por volume.",
                )
            if cleaned_data.get("dose_ml") is None:
                self.add_error(
                    "dose_ml",
                    "Informe o volume de cada dose em mL.",
                )

        if sale_form == "portion":
            if stock_dimension != "weight":
                self.add_error(
                    "stock_dimension",
                    "Produtos vendidos por porção precisam controlar estoque por peso.",
                )
            if cleaned_data.get("portion_g") is None:
                self.add_error(
                    "portion_g",
                    "Informe o peso de cada porção em gramas.",
                )

        if cleaned_data.get("minimum_quantity") is None:
            cleaned_data["minimum_quantity"] = Decimal("0")

        if cleaned_data.get("product_type") is None and inventory_role:
            cleaned_data["product_type"] = (
                "internal_use" if inventory_role == "input" else "sale"
            )

        cleaned_data["preparation_mode"] = preparation_mode
        return cleaned_data


class StockEntryForm(forms.Form):
    PRICE_MODES = (
        ("total", "Pre\u00e7o total"),
        ("per_unit", "Pre\u00e7o por medida"),
    )

    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        widget=forms.HiddenInput,
        error_messages={
            "required": "Selecione um produto.",
            "invalid_choice": "Selecione um produto v\u00e1lido.",
        },
    )
    input_quantity = CommaDecimalField(
        max_digits=20,
        decimal_places=6,
        error_messages={
            "required": "Informe a quantidade.",
            "invalid": "Informe uma quantidade v\u00e1lida.",
            "max_digits": "Informe uma quantidade v\u00e1lida.",
            "max_decimal_places": "Use no m\u00e1ximo seis casas decimais.",
        },
    )
    input_unit = forms.ChoiceField(
        choices=(("", "Selecione"), *QUANTITY_UNIT_CHOICES),
        error_messages={
            "required": "Informe a unidade.",
            "invalid_choice": "Informe uma unidade v\u00e1lida.",
        },
    )
    price_mode = forms.ChoiceField(
        choices=PRICE_MODES,
        initial="total",
        widget=forms.RadioSelect,
        error_messages={
            "required": "Selecione como deseja informar o pre\u00e7o.",
            "invalid_choice": "Selecione uma forma de pre\u00e7o v\u00e1lida.",
        },
    )
    price = CommaDecimalField(
        max_digits=20,
        decimal_places=10,
        error_messages={
            "required": "Informe o pre\u00e7o da entrada.",
            "invalid": "Informe um pre\u00e7o v\u00e1lido.",
            "max_digits": "Informe um pre\u00e7o v\u00e1lido.",
            "max_decimal_places": "Use no m\u00e1ximo dez casas decimais.",
        },
    )
    entry_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={
            "required": "Informe a data da entrada.",
            "invalid": "Informe uma data de entrada v\u00e1lida.",
        },
    )
    expiration_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        error_messages={"invalid": "Informe uma validade v\u00e1lida."},
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea,
    )

    def __init__(self, *args, company, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            company=company,
            active=True,
        ).order_by("name", "id")
        self.fields["entry_date"].initial = timezone.localdate
        self.fields["input_quantity"].widget.attrs.update(
            {"inputmode": "decimal", "placeholder": "Ex: 30"}
        )
        self.fields["price"].widget.attrs.update(
            {"inputmode": "decimal", "placeholder": "Ex: 750,00"}
        )
        self.fields["notes"].widget.attrs.update(
            {"placeholder": "Ex: compra no atacado, reposi\u00e7\u00e3o para s\u00e1bado..."}
        )

    def clean_input_quantity(self):
        quantity = self.cleaned_data["input_quantity"]
        if not quantity.is_finite():
            raise forms.ValidationError("Informe uma quantidade v\u00e1lida.")
        if quantity <= 0:
            raise forms.ValidationError("A quantidade deve ser maior que zero.")
        return quantity

    def clean_price(self):
        price = self.cleaned_data["price"]
        if not price.is_finite():
            raise forms.ValidationError("Informe um pre\u00e7o v\u00e1lido.")
        if price < 0:
            raise forms.ValidationError("O pre\u00e7o n\u00e3o pode ser negativo.")
        return price

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        quantity = cleaned_data.get("input_quantity")
        unit = cleaned_data.get("input_unit")
        if product is None or quantity is None or not unit:
            return cleaned_data

        if unit not in units_for_dimension(product.stock_dimension):
            self.add_error(
                "input_unit",
                "A unidade informada \u00e9 incompat\u00edvel com a dimens\u00e3o de estoque "
                "deste produto.",
            )
            return cleaned_data

        try:
            cleaned_data["normalized_quantity"] = normalize_quantity(
                quantity,
                unit,
            )
        except QuantityConversionError:
            self.add_error("input_quantity", "Informe uma quantidade v\u00e1lida.")

        return cleaned_data


class ProductComponentForm(forms.Form):
    component_id = forms.IntegerField(
        required=False,
        widget=forms.HiddenInput,
    )
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
            Product.objects.filter(company=company, active=True)
            .exclude(inventory_role="prepared")
            .select_related("unit")
            .order_by("inventory_role", "name", "id")
        )
        self.fields["quantity"].widget.attrs.update(
            {"inputmode": "decimal", "placeholder": "Ex: 50"}
        )

    def has_changed(self):
        if self.is_bound:
            component_id = self.data.get(self.add_prefix("component_id"), "")
            ingredient = self.data.get(self.add_prefix("ingredient"), "")
            quantity = self.data.get(self.add_prefix("quantity"), "")
            delete = self.data.get(self.add_prefix("DELETE"), "")
            if str(component_id).strip() or str(delete).strip():
                return True
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
                "A unidade escolhida não corresponde ao tipo de estoque deste ingrediente.",
            )

        return cleaned_data


class BaseProductComponentFormSet(forms.BaseFormSet):
    def __init__(self, *args, existing_component_ids=None, **kwargs):
        self.existing_component_ids = set(existing_component_ids or ())
        super().__init__(*args, **kwargs)

    def clean(self):
        super().clean()
        submitted_component_ids = []
        for form in self.forms:
            data = form.cleaned_data
            if not data:
                continue
            component_id = data.get("component_id")
            if component_id is not None:
                submitted_component_ids.append(component_id)

        if len(submitted_component_ids) != len(set(submitted_component_ids)):
            raise forms.ValidationError(
                "A receita contém uma referência de ingrediente repetida."
            )
        if set(submitted_component_ids) != self.existing_component_ids:
            raise forms.ValidationError(
                "A receita mudou desde que a página foi aberta. Recarregue e tente novamente."
            )
        if any(self.errors):
            return

        ingredient_ids = set()
        for form in self.forms:
            data = form.cleaned_data
            if not data:
                continue
            if data.get("DELETE"):
                continue
            ingredient = data.get("ingredient")
            if ingredient is None:
                continue
            if ingredient.pk in ingredient_ids:
                raise forms.ValidationError(
                    f"O ingrediente {ingredient.name} foi informado mais de uma vez."
                )
            ingredient_ids.add(ingredient.pk)

ProductComponentFormSet = formset_factory(
    ProductComponentForm,
    formset=BaseProductComponentFormSet,
    extra=1,
    can_delete=True,
)


class ProductionForm(forms.Form):
    planned_quantity = CommaDecimalField(
        max_digits=20,
        decimal_places=6,
        min_value=Decimal("0.000001"),
        label="Quantidade planejada",
        widget=forms.NumberInput(attrs={"step": "0.000001", "min": "0.000001"}),
    )
    produced_quantity = CommaDecimalField(
        max_digits=20,
        decimal_places=6,
        min_value=Decimal("0.000001"),
        label="Quantidade realmente produzida",
        widget=forms.NumberInput(attrs={"step": "0.000001", "min": "0.000001"}),
    )
    production_date = forms.DateField(
        label="Data da produção",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    expiration_date = forms.DateField(
        required=False,
        label="Validade do lote produzido",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    notes = forms.CharField(
        required=False,
        label="Observação",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean(self):
        cleaned_data = super().clean()
        production_date = cleaned_data.get("production_date")
        expiration_date = cleaned_data.get("expiration_date")
        if (
            production_date is not None
            and expiration_date is not None
            and expiration_date < production_date
        ):
            self.add_error(
                "expiration_date",
                "A validade não pode ser anterior à data da produção.",
            )
        return cleaned_data


class ProductionConsumptionForm(forms.Form):
    component_id = forms.IntegerField(widget=forms.HiddenInput)
    actual_quantity = CommaDecimalField(
        max_digits=20,
        decimal_places=6,
        min_value=Decimal("0.000001"),
        label="Consumo real",
        widget=forms.NumberInput(attrs={"step": "0.000001", "min": "0.000001"}),
    )
    loss_quantity = CommaDecimalField(
        max_digits=20,
        decimal_places=6,
        min_value=Decimal("0"),
        required=False,
        initial=Decimal("0"),
        label="Perda dentro do consumo",
        widget=forms.NumberInput(attrs={"step": "0.000001", "min": "0"}),
    )

    def clean(self):
        cleaned_data = super().clean()
        actual = cleaned_data.get("actual_quantity")
        loss = cleaned_data.get("loss_quantity") or Decimal("0")
        cleaned_data["loss_quantity"] = loss
        if actual is not None and loss > actual:
            self.add_error(
                "loss_quantity",
                "A perda não pode superar o consumo real.",
            )
        return cleaned_data


class BaseProductionConsumptionFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        component_ids = [
            form.cleaned_data.get("component_id")
            for form in self.forms
            if form.cleaned_data
        ]
        if len(component_ids) != len(set(component_ids)):
            raise forms.ValidationError(
                "Cada componente deve aparecer exatamente uma vez."
            )


ProductionConsumptionFormSet = formset_factory(
    ProductionConsumptionForm,
    formset=BaseProductionConsumptionFormSet,
    extra=0,
)


__all__ = [
    "ProductComponentForm",
    "ProductComponentFormSet",
    "ProductCreateForm",
    "ProductionConsumptionForm",
    "ProductionConsumptionFormSet",
    "ProductionForm",
    "StockEntryForm",
]
