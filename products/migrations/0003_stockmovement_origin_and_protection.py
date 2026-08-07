import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0002_alter_stockmovement_movement_type"),
        ("sales", "0002_sale_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="stockmovement",
            name="stock_entry",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="movements",
                to="products.stockentry",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="reversal_of",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reversal",
                to="products.stockmovement",
            ),
        ),
        migrations.AddField(
            model_name="stockmovement",
            name="sale_item",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="stock_movements",
                to="sales.saleitem",
            ),
        ),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.UniqueConstraint(
                condition=models.Q(("movement_type", "sale")),
                fields=("sale_item", "stock_entry"),
                name="uniq_sale_item_stock_entry",
            ),
        ),
    ]
