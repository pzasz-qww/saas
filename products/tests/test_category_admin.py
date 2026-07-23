from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from products.admin import CategoryAdmin, ProductAdmin, ProductAdminForm
from products.models import Category, Product

from .helpers import (
    make_category,
    make_company,
    make_product,
    make_unit,
    make_user,
)


class CategoryAdminCompanyIsolationTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Empresa principal")
        self.other_company = make_company(name="Outra empresa")
        self.user = make_user(
            company=self.company,
            is_staff=True,
        )
        self.request = RequestFactory().get("/admin/products/category/")
        self.request.user = self.user
        self.site = AdminSite()
        self.category_admin = CategoryAdmin(Category, self.site)
        self.product_admin = ProductAdmin(Product, self.site)

        self.own_category = make_category(
            company=self.company,
            name="Categoria local",
        )
        self.foreign_category = make_category(
            company=self.other_company,
            name="Categoria estrangeira",
        )
        self.own_unit = make_unit(company=self.company)
        self.foreign_unit = make_unit(company=self.other_company)
        self.own_product = make_product(
            company=self.company,
            unit=self.own_unit,
            category=self.own_category,
            name="Produto local",
        )
        self.foreign_product = make_product(
            company=self.other_company,
            unit=self.foreign_unit,
            category=self.foreign_category,
            name="Produto estrangeiro",
        )

    def test_category_and_product_querysets_are_scoped_to_operator_company(self):
        category_queryset = self.category_admin.get_queryset(self.request)
        product_queryset = self.product_admin.get_queryset(self.request)

        self.assertQuerySetEqual(
            category_queryset,
            [self.own_category],
            ordered=False,
        )
        self.assertQuerySetEqual(
            product_queryset,
            [self.own_product],
            ordered=False,
        )

    def test_product_category_and_unit_choices_are_scoped_to_company(self):
        category_field = self.product_admin.formfield_for_foreignkey(
            Product._meta.get_field("category"),
            self.request,
        )
        unit_field = self.product_admin.formfield_for_foreignkey(
            Product._meta.get_field("unit"),
            self.request,
        )

        self.assertQuerySetEqual(
            category_field.queryset,
            [self.own_category],
            ordered=False,
        )
        self.assertQuerySetEqual(
            unit_field.queryset,
            [self.own_unit],
            ordered=False,
        )

    def test_product_admin_form_rejects_forged_foreign_category(self):
        form = ProductAdminForm(
            data={
                "company": str(self.company.pk),
                "name": "Produto forjado",
                "category": str(self.foreign_category.pk),
                "category_legacy": "Categoria estrangeira",
                "product_type": "sale",
                "unit": str(self.own_unit.pk),
                "sale_price": "10.00",
                "minimum_quantity": "0.00",
                "active": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("category", form.errors)
        self.assertIn("empresa", form.errors["category"][0].lower())

    def test_admin_save_derives_category_company_from_operator(self):
        unsaved = Category(
            company=self.other_company,
            name="Criada pelo operador",
        )

        self.category_admin.save_model(
            self.request,
            unsaved,
            form=None,
            change=False,
        )

        self.assertEqual(unsaved.company, self.company)
        self.assertTrue(
            Category.objects.filter(
                company=self.company,
                name="Criada pelo operador",
            ).exists()
        )
        self.assertFalse(
            Category.objects.filter(
                company=self.other_company,
                name="Criada pelo operador",
            ).exists()
        )

    def test_category_admin_reports_equivalent_name_as_form_error(self):
        form_class = self.category_admin.get_form(self.request)
        form = form_class(
            data={
                "name": "  categoria   LOCAL  ",
                "active": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)
        self.assertIn("equivalente", form.errors["name"][0].lower())

    def test_superuser_keeps_global_visibility_and_choices(self):
        superuser = get_user_model().objects.create_superuser(
            username="admin-global",
            email="admin@example.com",
            password="secret",
        )
        request = RequestFactory().get("/admin/products/category/")
        request.user = superuser

        category_queryset = self.category_admin.get_queryset(request)
        product_queryset = self.product_admin.get_queryset(request)
        category_field = self.product_admin.formfield_for_foreignkey(
            Product._meta.get_field("category"),
            request,
        )

        self.assertQuerySetEqual(
            category_queryset,
            [self.own_category, self.foreign_category],
            ordered=False,
        )
        self.assertQuerySetEqual(
            product_queryset,
            [self.own_product, self.foreign_product],
            ordered=False,
        )
        self.assertQuerySetEqual(
            category_field.queryset,
            [self.own_category, self.foreign_category],
            ordered=False,
        )

    def test_user_without_company_sees_no_category_or_product(self):
        user_without_profile = get_user_model().objects.create_user(
            username="sem-empresa",
            password="secret",
            is_staff=True,
        )
        request = RequestFactory().get("/admin/products/category/")
        request.user = user_without_profile

        self.assertFalse(
            self.category_admin.get_queryset(request).exists()
        )
        self.assertFalse(
            self.product_admin.get_queryset(request).exists()
        )
