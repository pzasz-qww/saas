from decimal import Decimal
from itertools import count

from django.contrib.auth import get_user_model

from accounts.models import Profile
from companies.models import Company
from products.category_services import resolve_category
from products.models import Product, StockEntry, Unit


D = Decimal
_sequence = count(1)


def unique(prefix):
    return f"{prefix}-{next(_sequence)}"


def make_company(*, name=None):
    return Company.objects.create(name=name or unique("Empresa"))


def make_user(*, company, role="owner", username=None, is_staff=False):
    user = get_user_model().objects.create_user(
        username=username or unique("usuario"),
        password="test-password",
        is_staff=is_staff,
    )
    Profile.objects.create(user=user, company=company, role=role)
    return user


def make_unit(*, company, name=None, symbol=None):
    suffix = next(_sequence)
    return Unit.objects.create(
        company=company,
        name=name or f"Unidade {suffix}",
        symbol=symbol or f"u{suffix}",
    )


def make_category(*, company, name="Testes"):
    return resolve_category(company=company, raw_name=name)


def make_product(
    *,
    company,
    unit=None,
    category=None,
    category_name=None,
    name=None,
    product_type="sale",
    sale_price="10.00",
    minimum_quantity="0.00",
    active=True,
    inventory_role="direct",
    sale_form="unit",
    stock_dimension="count",
    unit_description="",
    dose_ml=None,
    portion_g=None,
    preparation_mode=None,
):
    if category is None and category_name is not None:
        category = make_category(company=company, name=category_name)

    return Product.objects.create(
        company=company,
        unit=unit or make_unit(company=company),
        name=name or unique("Produto"),
        category=category,
        category_legacy=category.name if category else None,
        product_type=product_type,
        inventory_role=inventory_role,
        sale_form=sale_form,
        stock_dimension=stock_dimension,
        unit_description=unit_description,
        dose_ml=D(dose_ml) if dose_ml is not None else None,
        portion_g=D(portion_g) if portion_g is not None else None,
        preparation_mode=preparation_mode,
        sale_price=D(sale_price),
        minimum_quantity=D(minimum_quantity),
        active=active,
    )


def make_entry(*, product, quantity="5.00", total_cost=None):
    quantity = D(quantity)
    return StockEntry.objects.create(
        company=product.company,
        product=product,
        total_cost=D(total_cost) if total_cost is not None else quantity,
        quantity_added=quantity,
        remaining_quantity=quantity,
    )
