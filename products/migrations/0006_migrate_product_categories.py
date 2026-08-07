import unicodedata

from django.db import migrations


BATCH_SIZE = 500
VISIBLE_NAME_MAX_LENGTH = 80
NORMALIZED_NAME_MAX_LENGTH = 255


def clean_category_name(value):
    return " ".join(str(value or "").split())


def normalize_category_name(value):
    cleaned_name = clean_category_name(value)
    decomposed_name = unicodedata.normalize("NFD", cleaned_name)
    name_without_accents = "".join(
        character
        for character in decomposed_name
        if not unicodedata.combining(character)
    )
    return name_without_accents.casefold()


def migrate_product_categories(apps, schema_editor):
    Category = apps.get_model("products", "Category")
    Product = apps.get_model("products", "Product")
    database_alias = schema_editor.connection.alias

    category_ids = {
        (category.company_id, category.normalized_name): category.id
        for category in Category.objects.using(database_alias)
        .only("id", "company", "normalized_name")
        .order_by("company_id", "id")
        .iterator(chunk_size=BATCH_SIZE)
    }
    products_to_update = []

    products = (
        Product.objects.using(database_alias)
        .only("id", "company", "category_legacy", "category")
        .order_by("company_id", "id")
        .iterator(chunk_size=BATCH_SIZE)
    )

    for product in products:
        visible_name = clean_category_name(product.category_legacy)
        normalized_name = normalize_category_name(visible_name)
        category_id = None

        if visible_name and normalized_name:
            if len(visible_name) > VISIBLE_NAME_MAX_LENGTH:
                raise RuntimeError(
                    "A categoria legada do produto "
                    f"{product.id} excede o limite do nome visível."
                )

            if len(normalized_name) > NORMALIZED_NAME_MAX_LENGTH:
                raise RuntimeError(
                    "A categoria legada do produto "
                    f"{product.id} excede o limite após a normalização."
                )

            category_key = (product.company_id, normalized_name)
            category_id = category_ids.get(category_key)

            if category_id is None:
                category = Category.objects.using(database_alias).create(
                    company_id=product.company_id,
                    name=visible_name,
                    normalized_name=normalized_name,
                )
                category_id = category.id
                category_ids[category_key] = category_id

        product.category_id = category_id
        products_to_update.append(product)

        if len(products_to_update) >= BATCH_SIZE:
            Product.objects.using(database_alias).bulk_update(
                products_to_update,
                ("category",),
                batch_size=BATCH_SIZE,
            )
            products_to_update.clear()

    if products_to_update:
        Product.objects.using(database_alias).bulk_update(
            products_to_update,
            ("category",),
            batch_size=BATCH_SIZE,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0005_product_category_fk"),
    ]

    operations = [
        migrations.RunPython(
            migrate_product_categories,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
