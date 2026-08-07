import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0003_stockmovement_origin_and_protection"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=80)),
                (
                    "normalized_name",
                    models.CharField(editable=False, max_length=255),
                ),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="product_categories",
                        to="companies.company",
                    ),
                ),
            ],
            options={
                "verbose_name": "Categoria",
                "verbose_name_plural": "Categorias",
                "ordering": ("name", "id"),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("company", "normalized_name"),
                        name="uniq_category_company_norm",
                    ),
                    models.CheckConstraint(
                        condition=(
                            ~models.Q(name="") & ~models.Q(normalized_name="")
                        ),
                        name="category_names_not_empty",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["normalized_name"],
                        name="category_norm_idx",
                    ),
                    models.Index(
                        fields=["company", "active", "name"],
                        name="category_company_list_idx",
                    ),
                ],
            },
        ),
    ]
