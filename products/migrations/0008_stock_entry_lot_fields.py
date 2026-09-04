from django.db import migrations, models
from django.db.models import F
import django.utils.timezone


def populate_legacy_lot_fields(apps, schema_editor):
    StockEntry = apps.get_model("products", "StockEntry")
    base_units = {
        "count": "unit",
        "weight": "g",
        "volume": "mL",
    }
    for dimension, base_unit in base_units.items():
        StockEntry.objects.filter(
            product__stock_dimension=dimension,
        ).update(
            input_quantity=F("quantity_added"),
            input_unit=base_unit,
            base_unit=base_unit,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0007_productcomponent_product_dose_ml_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="stockentry",
            name="base_unit",
            field=models.CharField(
                choices=[
                    ("unit", "unidade"),
                    ("mg", "mg"),
                    ("g", "g"),
                    ("kg", "kg"),
                    ("mL", "mL"),
                    ("L", "L"),
                ],
                default="",
                help_text="Unidade-base da quantidade oficial do lote.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="entry_date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="expiration_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="input_quantity",
            field=models.DecimalField(
                decimal_places=6,
                default=0,
                help_text="Quantidade originalmente informada pelo usu\u00e1rio.",
                max_digits=20,
            ),
        ),
        migrations.AddField(
            model_name="stockentry",
            name="input_unit",
            field=models.CharField(
                choices=[
                    ("unit", "unidade"),
                    ("mg", "mg"),
                    ("g", "g"),
                    ("kg", "kg"),
                    ("mL", "mL"),
                    ("L", "L"),
                ],
                default="",
                help_text="Unidade originalmente informada pelo usu\u00e1rio.",
                max_length=10,
            ),
        ),
        migrations.RunPython(
            populate_legacy_lot_fields,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="stockentry",
            constraint=models.CheckConstraint(
                condition=models.Q(("input_quantity__gt", 0)),
                name="stock_entry_input_quantity_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockentry",
            constraint=models.CheckConstraint(
                condition=models.Q(("quantity_added__gt", 0)),
                name="stock_entry_normalized_quantity_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockentry",
            constraint=models.CheckConstraint(
                condition=models.Q(("remaining_quantity__gte", 0)),
                name="stock_entry_remaining_quantity_nonnegative",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockentry",
            constraint=models.CheckConstraint(
                condition=models.Q(("remaining_quantity__lte", F("quantity_added"))),
                name="stock_entry_remaining_not_above_initial",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockentry",
            constraint=models.CheckConstraint(
                condition=models.Q(("total_cost__gte", 0)),
                name="stock_entry_total_cost_nonnegative",
            ),
        ),
    ]
