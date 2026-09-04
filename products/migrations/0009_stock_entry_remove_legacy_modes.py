from django.db import migrations, models
from django.db.models import F


def fill_missing_remaining_quantity(apps, schema_editor):
    StockEntry = apps.get_model("products", "StockEntry")
    StockEntry.objects.filter(remaining_quantity__isnull=True).update(
        remaining_quantity=F("quantity_added"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0008_stock_entry_lot_fields"),
    ]

    operations = [
        migrations.RunPython(
            fill_missing_remaining_quantity,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="stockentry",
            name="entry_mode",
        ),
        migrations.RemoveField(
            model_name="stockentry",
            name="package_cost",
        ),
        migrations.RemoveField(
            model_name="stockentry",
            name="package_quantity",
        ),
        migrations.AlterField(
            model_name="stockentry",
            name="remaining_quantity",
            field=models.DecimalField(decimal_places=6, max_digits=20),
        ),
    ]
