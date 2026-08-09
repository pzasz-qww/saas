from django.core.exceptions import ValidationError

from .category_names import clean_category_name, normalize_category_name
from .models import Category


def resolve_category(*, company, raw_name):
    """Resolve free text to a category owned by ``company``.

    The database uniqueness constraint makes ``get_or_create`` safe when two
    requests try to introduce equivalent names at the same time.
    """
    cleaned_name = clean_category_name(raw_name)
    if not cleaned_name:
        return None

    normalized_name = normalize_category_name(cleaned_name)
    if not normalized_name:
        raise ValidationError("Informe um nome de categoria válido.")

    category, _created = Category.objects.get_or_create(
        company=company,
        normalized_name=normalized_name,
        defaults={"name": cleaned_name},
    )
    return category
