"""Operational expansion and availability for product compositions."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from django.db import connection
from django.db.models import Sum

from .models import Product, ProductComponent, StockEntry
from .quantities import QuantityConversionError, normalize_quantity
from .sale_quantities import (
    PhysicalConsumption,
    PhysicalSaleQuantityError,
    get_physical_consumption,
    get_sale_availability,
)


ZERO = Decimal("0")
PHYSICAL_QUANTUM = Decimal("0.000001")


class RecipeServiceError(ValueError):
    """Raised when a composition cannot safely participate in stock."""


class InvalidOperationalRecipe(RecipeServiceError):
    """Raised for empty, inactive, cross-tenant, or inconsistent recipes."""


@dataclass(frozen=True, slots=True)
class ExpandedProductComponent:
    source_component: ProductComponent
    ingredient: Product
    quantity_per_sale_unit: Decimal
    total_quantity: Decimal
    base_unit: str


@dataclass(frozen=True, slots=True)
class SaleLineConsumption:
    item: object
    product: Product
    own_consumption: PhysicalConsumption | None
    components: tuple[ExpandedProductComponent, ...]

    @property
    def uses_components(self):
        return bool(self.components)


@dataclass(frozen=True, slots=True)
class SaleConsumptionPlan:
    lines: tuple[SaleLineConsumption, ...]
    product_quantities: dict[int, Decimal]
    requirement_products: dict[int, Product]
    requirement_base_units: dict[int, str]


@dataclass(frozen=True, slots=True)
class ComponentAvailability:
    source_component: ProductComponent
    ingredient: Product
    quantity_per_sale_unit: Decimal
    physical_stock: Decimal
    available_quantity: Decimal
    base_unit: str


@dataclass(frozen=True, slots=True)
class ProductAvailability:
    product: Product
    available_quantity: Decimal
    limiting_component: ComponentAvailability | None
    component_availability: tuple[ComponentAvailability, ...]
    source: str


@dataclass(frozen=True, slots=True)
class ProductAvailabilityBatch:
    availability_by_product: dict[int, ProductAvailability]
    errors_by_product: dict[int, RecipeServiceError]


def _company_id(company):
    company_id = getattr(company, "pk", company)
    if company_id is None:
        raise InvalidOperationalRecipe("A empresa precisa estar salva.")
    return company_id


def _exact_physical_quantity(value, *, label):
    try:
        quantized = value.quantize(PHYSICAL_QUANTUM)
    except ArithmeticError:
        raise InvalidOperationalRecipe(f"{label} possui precisão inválida.") from None
    if quantized != value:
        raise InvalidOperationalRecipe(
            f"{label} excede a precisão física de seis casas decimais."
        )
    return quantized


def _item_value(item, field):
    if isinstance(item, dict):
        return item.get(field)
    return getattr(item, field, None)


def _load_products(*, company_id, product_ids, lock):
    queryset = Product.objects.filter(
        company_id=company_id,
        pk__in=sorted(set(product_ids)),
    ).order_by("id")
    if lock:
        queryset = queryset.select_for_update()
    products = list(queryset)
    product_by_id = {product.pk: product for product in products}
    missing = sorted(set(product_ids) - set(product_by_id))
    if missing:
        missing_text = ", ".join(str(product_id) for product_id in missing)
        raise InvalidOperationalRecipe(
            f"Produto(s) fora da empresa informada: {missing_text}."
        )
    return product_by_id


def _normalized_component(component, *, product, ingredient):
    if component.company_id != product.company_id:
        raise InvalidOperationalRecipe(
            f"O componente #{component.pk} pertence a outra empresa."
        )
    if component.product_id != product.pk:
        raise InvalidOperationalRecipe(
            f"O componente #{component.pk} pertence a outro produto."
        )
    if ingredient.company_id != product.company_id:
        raise InvalidOperationalRecipe(
            f"O ingrediente {ingredient.name} pertence a outra empresa."
        )
    if ingredient.inventory_role == "prepared":
        raise InvalidOperationalRecipe(
            f"O ingrediente {ingredient.name} é preparado e não pode ser uma subreceita."
        )
    if not ingredient.active:
        raise InvalidOperationalRecipe(
            f"O ingrediente {ingredient.name} está inativo."
        )

    try:
        normalized = normalize_quantity(component.quantity, component.unit)
    except QuantityConversionError as error:
        raise InvalidOperationalRecipe(
            f"O componente {ingredient.name} possui quantidade inválida: {error}"
        ) from error
    if normalized.dimension != ingredient.stock_dimension:
        raise InvalidOperationalRecipe(
            f"A unidade do componente {ingredient.name} é incompatível com seu estoque."
        )
    return normalized


def build_sale_consumption_plan(*, items, company, lock=False):
    """Expand all sale lines and aggregate every physical stock requirement."""
    if lock and not connection.in_atomic_block:
        raise InvalidOperationalRecipe(
            "O plano bloqueado precisa ser criado dentro de uma transação."
        )

    company_id = _company_id(company)
    items = list(items)
    if not items:
        raise InvalidOperationalRecipe("O pedido não possui itens.")

    product_ids = []
    for item in items:
        product = _item_value(item, "product")
        product_id = _item_value(item, "product_id")
        if product_id is None and product is not None:
            product_id = product.pk
        if product_id is None:
            raise InvalidOperationalRecipe("Item sem produto.")
        item_company_id = _item_value(item, "company_id")
        if item_company_id is not None and item_company_id != company_id:
            raise InvalidOperationalRecipe(
                f"O item do produto #{product_id} pertence a outra empresa."
            )
        product_ids.append(product_id)

    sold_products = _load_products(
        company_id=company_id,
        product_ids=product_ids,
        lock=lock,
    )
    on_demand_ids = {
        product.pk
        for product in sold_products.values()
        if product.inventory_role == "prepared"
        and product.preparation_mode == "on_demand"
    }

    component_queryset = ProductComponent.objects.filter(
        company_id=company_id,
        product_id__in=on_demand_ids,
    ).order_by("product_id", "ingredient_id", "id")
    if lock:
        component_queryset = component_queryset.select_for_update()
    components = list(component_queryset)

    ingredient_ids = [component.ingredient_id for component in components]
    ingredients = _load_products(
        company_id=company_id,
        product_ids=ingredient_ids,
        lock=lock,
    ) if ingredient_ids else {}

    components_by_product = defaultdict(list)
    seen_pairs = set()
    for component in components:
        pair = (component.product_id, component.ingredient_id)
        if pair in seen_pairs:
            raise InvalidOperationalRecipe(
                "A receita possui ingredientes duplicados."
            )
        seen_pairs.add(pair)
        components_by_product[component.product_id].append(component)

    totals = defaultdict(lambda: ZERO)
    requirement_products = {}
    requirement_base_units = {}
    lines = []

    for item in items:
        product_id = _item_value(item, "product_id")
        if product_id is None:
            product_id = _item_value(item, "product").pk
        product = sold_products[product_id]
        quantity = _item_value(item, "quantity")

        if product_id in on_demand_ids:
            product_components = components_by_product.get(product_id, ())
            if not product_components:
                raise InvalidOperationalRecipe(
                    f"O produto preparado {product.name} não possui componentes."
                )

            expanded_components = []
            for component in product_components:
                ingredient = ingredients[component.ingredient_id]
                normalized = _normalized_component(
                    component,
                    product=product,
                    ingredient=ingredient,
                )
                try:
                    commercial_quantity = get_physical_consumption(
                        product,
                        quantity,
                    ).sale_quantity
                except PhysicalSaleQuantityError as error:
                    raise InvalidOperationalRecipe(str(error)) from error
                quantity_per_sale_unit = _exact_physical_quantity(
                    normalized.quantity,
                    label=f"A quantidade do componente {ingredient.name}",
                )
                total_quantity = _exact_physical_quantity(
                    quantity_per_sale_unit * commercial_quantity,
                    label=f"O consumo total do componente {ingredient.name}",
                )
                expanded = ExpandedProductComponent(
                    source_component=component,
                    ingredient=ingredient,
                    quantity_per_sale_unit=quantity_per_sale_unit,
                    total_quantity=total_quantity,
                    base_unit=normalized.base_unit,
                )
                expanded_components.append(expanded)
                totals[ingredient.pk] += total_quantity
                requirement_products[ingredient.pk] = ingredient
                requirement_base_units[ingredient.pk] = normalized.base_unit

            lines.append(
                SaleLineConsumption(
                    item=item,
                    product=product,
                    own_consumption=None,
                    components=tuple(expanded_components),
                )
            )
            continue

        try:
            own_consumption = get_physical_consumption(product, quantity)
        except PhysicalSaleQuantityError as error:
            raise InvalidOperationalRecipe(str(error)) from error
        totals[product.pk] += own_consumption.total_quantity
        requirement_products[product.pk] = product
        requirement_base_units[product.pk] = own_consumption.base_unit
        lines.append(
            SaleLineConsumption(
                item=item,
                product=product,
                own_consumption=own_consumption,
                components=(),
            )
        )

    return SaleConsumptionPlan(
        lines=tuple(lines),
        product_quantities=dict(sorted(totals.items())),
        requirement_products=requirement_products,
        requirement_base_units=requirement_base_units,
    )


def expand_product_components(product, sale_quantity, *, lock=False):
    """Expand one prepared product's recipe into physical component quantities."""
    if lock and not connection.in_atomic_block:
        raise InvalidOperationalRecipe(
            "A expansão bloqueada precisa ocorrer dentro de uma transação."
        )
    if product.pk is None or product.company_id is None:
        raise InvalidOperationalRecipe("O produto preparado precisa estar salvo.")

    product_queryset = Product.objects.filter(
        pk=product.pk,
        company_id=product.company_id,
    )
    if lock:
        product_queryset = product_queryset.select_for_update()
    locked_product = product_queryset.first()
    if locked_product is None:
        raise InvalidOperationalRecipe("O produto não pertence à empresa informada.")
    if locked_product.inventory_role != "prepared":
        raise InvalidOperationalRecipe(
            "Somente produtos preparados podem possuir receita operacional."
        )

    try:
        commercial_quantity = get_physical_consumption(
            locked_product,
            sale_quantity,
        ).sale_quantity
    except PhysicalSaleQuantityError as error:
        raise InvalidOperationalRecipe(str(error)) from error

    component_queryset = ProductComponent.objects.filter(
        company_id=locked_product.company_id,
        product_id=locked_product.pk,
    ).order_by("ingredient_id", "id")
    if lock:
        component_queryset = component_queryset.select_for_update()
    components = list(component_queryset)
    if not components:
        raise InvalidOperationalRecipe(
            f"O produto preparado {locked_product.name} não possui componentes."
        )

    ingredient_ids = [component.ingredient_id for component in components]
    ingredients = _load_products(
        company_id=locked_product.company_id,
        product_ids=ingredient_ids,
        lock=lock,
    )
    expanded_components = []
    seen_ingredients = set()
    for component in components:
        if component.ingredient_id in seen_ingredients:
            raise InvalidOperationalRecipe(
                "A receita possui ingredientes duplicados."
            )
        seen_ingredients.add(component.ingredient_id)
        ingredient = ingredients[component.ingredient_id]
        normalized = _normalized_component(
            component,
            product=locked_product,
            ingredient=ingredient,
        )
        quantity_per_sale_unit = _exact_physical_quantity(
            normalized.quantity,
            label=f"A quantidade do componente {ingredient.name}",
        )
        total_quantity = _exact_physical_quantity(
            quantity_per_sale_unit * commercial_quantity,
            label=f"O consumo total do componente {ingredient.name}",
        )
        expanded_components.append(
            ExpandedProductComponent(
                source_component=component,
                ingredient=ingredient,
                quantity_per_sale_unit=quantity_per_sale_unit,
                total_quantity=total_quantity,
                base_unit=normalized.base_unit,
            )
        )
    return tuple(expanded_components)


def _component_based_availability(product, *, source):
    components = expand_product_components(product, Decimal("1"))
    ingredient_ids = [component.ingredient.pk for component in components]
    stock_by_product = dict(
        StockEntry.objects.filter(
            company_id=product.company_id,
            product_id__in=ingredient_ids,
            remaining_quantity__gt=ZERO,
        )
        .values("product_id")
        .annotate(total=Sum("remaining_quantity"))
        .values_list("product_id", "total")
    )

    component_availability = []
    for component in components:
        stock = stock_by_product.get(component.ingredient.pk, ZERO) or ZERO
        available = stock // component.quantity_per_sale_unit
        component_availability.append(
            ComponentAvailability(
                source_component=component.source_component,
                ingredient=component.ingredient,
                quantity_per_sale_unit=component.quantity_per_sale_unit,
                physical_stock=stock,
                available_quantity=available,
                base_unit=component.base_unit,
            )
        )

    limiting = min(
        component_availability,
        key=lambda item: (
            item.available_quantity,
            item.ingredient.name.casefold(),
            item.ingredient.pk,
        ),
    )
    return ProductAvailability(
        product=product,
        available_quantity=limiting.available_quantity,
        limiting_component=limiting,
        component_availability=tuple(component_availability),
        source=source,
    )


def get_product_availability(product):
    """Calculate direct or component-limited commercial availability."""
    if not (
        product.inventory_role == "prepared"
        and product.preparation_mode == "on_demand"
    ):
        availability = get_sale_availability(product)
        return ProductAvailability(
            product=product,
            available_quantity=availability.available_sale_quantity,
            limiting_component=None,
            component_availability=(),
            source="own_stock",
        )

    return _component_based_availability(product, source="components")


def get_products_availability(products, *, company):
    """Calculate sale availability for many products with bounded queries."""
    company_id = _company_id(company)
    products = list(products)
    product_by_id = {}
    errors_by_product = {}

    for product in products:
        if product.pk is None:
            continue
        if product.company_id != company_id:
            errors_by_product[product.pk] = InvalidOperationalRecipe(
                "O produto pertence a outra empresa."
            )
            continue
        product_by_id[product.pk] = product

    on_demand_ids = {
        product.pk
        for product in product_by_id.values()
        if product.inventory_role == "prepared"
        and product.preparation_mode == "on_demand"
    }
    components = list(
        ProductComponent.objects.filter(
            company_id=company_id,
            product_id__in=on_demand_ids,
        )
        .select_related("ingredient")
        .order_by("product_id", "ingredient_id", "id")
    )
    components_by_product = defaultdict(list)
    stock_product_ids = set(product_by_id) - on_demand_ids
    for component in components:
        components_by_product[component.product_id].append(component)
        stock_product_ids.add(component.ingredient_id)

    stock_by_product = dict(
        StockEntry.objects.filter(
            company_id=company_id,
            product_id__in=stock_product_ids,
            remaining_quantity__gt=ZERO,
        )
        .values("product_id")
        .annotate(total=Sum("remaining_quantity"))
        .values_list("product_id", "total")
    )

    availability_by_product = {}
    for product in product_by_id.values():
        try:
            if product.pk not in on_demand_ids:
                sale_availability = get_sale_availability(
                    product,
                    stock_by_product.get(product.pk, ZERO) or ZERO,
                )
                availability_by_product[product.pk] = ProductAvailability(
                    product=product,
                    available_quantity=sale_availability.available_sale_quantity,
                    limiting_component=None,
                    component_availability=(),
                    source="own_stock",
                )
                continue

            product_components = components_by_product.get(product.pk, ())
            if not product_components:
                raise InvalidOperationalRecipe(
                    f"O produto preparado {product.name} não possui componentes."
                )

            try:
                get_physical_consumption(product, Decimal("1"))
            except PhysicalSaleQuantityError as error:
                raise InvalidOperationalRecipe(str(error)) from error

            component_availability = []
            seen_ingredients = set()
            for component in product_components:
                if component.ingredient_id in seen_ingredients:
                    raise InvalidOperationalRecipe(
                        "A receita possui ingredientes duplicados."
                    )
                seen_ingredients.add(component.ingredient_id)
                normalized = _normalized_component(
                    component,
                    product=product,
                    ingredient=component.ingredient,
                )
                quantity_per_sale_unit = _exact_physical_quantity(
                    normalized.quantity,
                    label=f"A quantidade do componente {component.ingredient.name}",
                )
                physical_stock = (
                    stock_by_product.get(component.ingredient_id, ZERO) or ZERO
                )
                component_availability.append(
                    ComponentAvailability(
                        source_component=component,
                        ingredient=component.ingredient,
                        quantity_per_sale_unit=quantity_per_sale_unit,
                        physical_stock=physical_stock,
                        available_quantity=(
                            physical_stock // quantity_per_sale_unit
                        ),
                        base_unit=normalized.base_unit,
                    )
                )

            limiting = min(
                component_availability,
                key=lambda item: (
                    item.available_quantity,
                    item.ingredient.name.casefold(),
                    item.ingredient.pk,
                ),
            )
            availability_by_product[product.pk] = ProductAvailability(
                product=product,
                available_quantity=limiting.available_quantity,
                limiting_component=limiting,
                component_availability=tuple(component_availability),
                source="components",
            )
        except RecipeServiceError as error:
            errors_by_product[product.pk] = error
        except PhysicalSaleQuantityError as error:
            errors_by_product[product.pk] = InvalidOperationalRecipe(str(error))

    return ProductAvailabilityBatch(
        availability_by_product=availability_by_product,
        errors_by_product=errors_by_product,
    )


def get_production_potential(product):
    """Return theoretical additional output for a pre-portioned product."""
    if not (
        product.inventory_role == "prepared"
        and product.preparation_mode == "pre_portioned"
    ):
        raise InvalidOperationalRecipe(
            "O potencial de produção exige produto preparado antecipadamente."
        )
    return _component_based_availability(
        product,
        source="production_potential",
    )


__all__ = [
    "ComponentAvailability",
    "ExpandedProductComponent",
    "InvalidOperationalRecipe",
    "ProductAvailability",
    "ProductAvailabilityBatch",
    "RecipeServiceError",
    "SaleConsumptionPlan",
    "SaleLineConsumption",
    "build_sale_consumption_plan",
    "expand_product_components",
    "get_product_availability",
    "get_products_availability",
    "get_production_potential",
]
