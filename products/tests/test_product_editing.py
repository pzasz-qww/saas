from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from orders.models import Order, OrderItem
from orders.services import approve_order, cancel_paid_order_with_stock_return
from products.models import ProductComponent
from products.production_services import create_production
from products.recipe_services import get_product_availability

from .helpers import make_company, make_entry, make_product, make_unit, make_user


D = Decimal


class ProductEditingTests(TestCase):
    def setUp(self):
        self.company = make_company(name="Bar da edição")
        self.user = make_user(company=self.company, role="owner")
        self.client.force_login(self.user)
        self.unit = make_unit(company=self.company, name="Unidade", symbol="un")
        self.drink = make_product(
            company=self.company,
            unit=self.unit,
            name="Drink da casa",
            sale_price="20",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )
        self.spirit = make_product(
            company=self.company,
            unit=self.unit,
            name="Base",
            product_type="internal_use",
            inventory_role="input",
        )
        self.lemon = make_product(
            company=self.company,
            unit=self.unit,
            name="Limão",
            product_type="internal_use",
            inventory_role="input",
        )
        self.spirit_component = ProductComponent.objects.create(
            company=self.company,
            product=self.drink,
            ingredient=self.spirit,
            quantity=D("2"),
            unit="unit",
        )
        self.lemon_component = ProductComponent.objects.create(
            company=self.company,
            product=self.drink,
            ingredient=self.lemon,
            quantity=D("1"),
            unit="unit",
        )
        self.spirit_entry = make_entry(product=self.spirit, quantity="40")
        self.lemon_entry = make_entry(product=self.lemon, quantity="8")

    def component_rows(self, product=None):
        product = product or self.drink
        return [
            {
                "component_id": str(component.pk),
                "ingredient": str(component.ingredient_id),
                "quantity": str(component.quantity),
                "unit": component.unit,
            }
            for component in product.components.order_by("id")
        ]

    def payload(self, product=None, *, rows=None, **overrides):
        product = product or self.drink
        if rows is None:
            rows = self.component_rows(product)
        data = {
            "name": product.name,
            "sale_price": str(product.sale_price),
            "sale_form": product.sale_form,
            "category": product.category.name if product.category_id else "",
            "product_type": product.product_type,
            "unit": str(product.unit_id),
            "inventory_role": product.inventory_role,
            "stock_dimension": product.stock_dimension,
            "unit_description": product.unit_description,
            "preparation_mode": product.preparation_mode or "",
            "minimum_quantity": str(product.minimum_quantity),
            "active_present": "1",
            "components-TOTAL_FORMS": str(len(rows)),
            "components-INITIAL_FORMS": str(product.components.count()),
            "components-MIN_NUM_FORMS": "0",
            "components-MAX_NUM_FORMS": "1000",
        }
        if product.active:
            data["active"] = "on"
        if product.dose_ml is not None:
            data["dose_ml"] = str(product.dose_ml)
        if product.portion_g is not None:
            data["portion_g"] = str(product.portion_g)
        for index, row in enumerate(rows):
            for field, value in row.items():
                data[f"components-{index}-{field}"] = value
        data.update(overrides)
        return data

    def edit_url(self, product=None):
        return reverse("products:product_edit", args=[(product or self.drink).pk])

    def test_edit_page_loads_product_recipe_and_current_availability(self):
        response = self.client.get(self.edit_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Editar produto")
        self.assertContains(response, "Como este item é utilizado")
        self.assertContains(response, "Estoque controlado em")
        self.assertContains(response, "Quando o produto é preparado")
        self.assertContains(response, "Disponível para venda:")
        self.assertContains(response, "Ingrediente limitante:")
        self.assertContains(response, "Limão")
        self.assertContains(response, "Esta alteração afetará somente novas vendas e produções.")
        self.assertContains(response, "O histórico existente será preservado.")
        self.assertContains(
            response,
            f'name="components-0-component_id" value="{self.spirit_component.pk}"',
        )

    def test_basic_product_data_can_be_edited(self):
        response = self.client.post(
            self.edit_url(),
            self.payload(name="Drink especial", sale_price="27,50"),
        )

        self.assertRedirects(
            response,
            self.edit_url(),
            fetch_redirect_response=False,
        )
        self.drink.refresh_from_db()
        self.assertEqual(self.drink.name, "Drink especial")
        self.assertEqual(self.drink.sale_price, D("27.50"))

    def test_new_ingredient_is_persisted_and_visible_after_reload(self):
        sugar = make_product(
            company=self.company,
            unit=self.unit,
            name="Açúcar",
            product_type="internal_use",
            inventory_role="input",
        )
        rows = self.component_rows()
        rows.append(
            {
                "ingredient": str(sugar.pk),
                "quantity": "3",
                "unit": "unit",
            }
        )

        response = self.client.post(self.edit_url(), self.payload(rows=rows))

        self.assertEqual(response.status_code, 302)
        component = self.drink.components.get(ingredient=sugar)
        self.assertEqual(component.quantity, D("3"))
        reload_response = self.client.get(self.edit_url())
        self.assertContains(
            reload_response,
            f'name="components-2-component_id" value="{component.pk}"',
        )

    def test_editing_component_recalculates_availability_and_limiter(self):
        rows = self.component_rows()
        rows[1]["quantity"] = "0.25"

        response = self.client.post(self.edit_url(), self.payload(rows=rows))

        self.assertEqual(response.status_code, 302)
        self.lemon_component.refresh_from_db()
        self.assertEqual(self.lemon_component.quantity, D("0.250000"))
        availability = get_product_availability(self.drink)
        self.assertEqual(availability.available_quantity, D("20"))
        self.assertEqual(availability.limiting_component.ingredient, self.spirit)

    def test_remove_persisted_ingredient_changes_future_recipe(self):
        rows = self.component_rows()
        rows[1]["DELETE"] = "on"

        response = self.client.post(self.edit_url(), self.payload(rows=rows))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ProductComponent.objects.filter(pk=self.lemon_component.pk).exists()
        )
        availability = get_product_availability(self.drink)
        self.assertEqual(availability.available_quantity, D("20"))
        self.assertEqual(availability.limiting_component.ingredient, self.spirit)
        reload_response = self.client.get(self.edit_url())
        persisted_ids = {
            initial["component_id"]
            for initial in reload_response.context["component_formset"].initial
        }
        self.assertNotIn(
            self.lemon_component.pk,
            persisted_ids,
        )

    def test_on_demand_recipe_cannot_be_saved_empty(self):
        rows = self.component_rows()
        for row in rows:
            row["DELETE"] = "on"

        response = self.client.post(
            self.edit_url(),
            self.payload(rows=rows, name="Não deve persistir"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Produto preparado sob demanda precisa de ao menos um componente.",
        )
        self.drink.refresh_from_db()
        self.assertEqual(self.drink.name, "Drink da casa")
        self.assertEqual(self.drink.components.count(), 2)

    def test_existing_empty_on_demand_recipe_can_be_corrected(self):
        empty_recipe = make_product(
            company=self.company,
            unit=self.unit,
            name="Receita incompleta",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )
        response = self.client.get(self.edit_url(empty_recipe))
        self.assertContains(response, "Receita ainda não configurada.")

        rows = [
            {
                "ingredient": str(self.spirit.pk),
                "quantity": "2",
                "unit": "unit",
            }
        ]
        response = self.client.post(
            self.edit_url(empty_recipe),
            self.payload(empty_recipe, rows=rows),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(empty_recipe.components.count(), 1)
        self.assertContains(response, "Disponível para venda:")
        self.assertContains(response, "20")

    def test_duplicate_and_invalid_components_do_not_change_recipe(self):
        duplicate_rows = self.component_rows()
        duplicate_rows[1]["ingredient"] = str(self.spirit.pk)
        response = self.client.post(
            self.edit_url(),
            self.payload(rows=duplicate_rows),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "foi informado mais de uma vez")

        invalid_rows = self.component_rows()
        invalid_rows[1]["quantity"] = "0"
        response = self.client.post(
            self.edit_url(),
            self.payload(rows=invalid_rows),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A quantidade deve ser positiva.")

        self.lemon_component.refresh_from_db()
        self.assertEqual(self.lemon_component.ingredient, self.lemon)
        self.assertEqual(self.lemon_component.quantity, D("1"))

    def test_empty_pre_portioned_recipe_can_be_corrected(self):
        pre_portioned = make_product(
            company=self.company,
            unit=self.unit,
            name="Espetinho pronto",
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        empty_response = self.client.get(self.edit_url(pre_portioned))
        self.assertContains(empty_response, "Receita ainda não configurada para produção.")

        rows = [
            {
                "ingredient": str(self.spirit.pk),
                "quantity": "2",
                "unit": "unit",
            }
        ]
        response = self.client.post(
            self.edit_url(pre_portioned),
            self.payload(pre_portioned, rows=rows),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(pre_portioned.components.count(), 1)
        self.assertContains(response, "Prontos para venda")
        self.assertContains(response, "Pode preparar")
        self.assertContains(response, "20")

    def test_cross_company_product_ingredient_and_component_ids_are_rejected(self):
        other_company = make_company(name="Outro bar")
        other_user_unit = make_unit(company=other_company)
        foreign_ingredient = make_product(
            company=other_company,
            unit=other_user_unit,
            name="Ingrediente confidencial",
            inventory_role="input",
        )
        foreign_product = make_product(
            company=other_company,
            unit=other_user_unit,
            name="Receita confidencial",
            inventory_role="prepared",
            preparation_mode="on_demand",
        )
        foreign_component = ProductComponent.objects.create(
            company=other_company,
            product=foreign_product,
            ingredient=foreign_ingredient,
            quantity=D("1"),
            unit="unit",
        )

        self.assertEqual(self.client.get(self.edit_url(foreign_product)).status_code, 404)

        foreign_ingredient_rows = self.component_rows()
        foreign_ingredient_rows[1]["ingredient"] = str(foreign_ingredient.pk)
        response = self.client.post(
            self.edit_url(),
            self.payload(rows=foreign_ingredient_rows),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione um ingrediente válido.")
        own_page = self.client.get(self.edit_url())
        self.assertNotContains(own_page, "Ingrediente confidencial")

        forged_rows = self.component_rows()
        forged_rows[1]["component_id"] = str(foreign_component.pk)
        response = self.client.post(
            self.edit_url(),
            self.payload(rows=forged_rows, name="Tentativa indevida"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A receita mudou desde que a página foi aberta.")
        self.drink.refresh_from_db()
        self.assertEqual(self.drink.name, "Drink da casa")
        self.assertEqual(self.drink.components.count(), 2)
        self.assertEqual(foreign_product.components.count(), 1)

        forged_rows[1]["DELETE"] = "on"
        delete_response = self.client.post(
            self.edit_url(),
            self.payload(rows=forged_rows),
        )
        self.assertEqual(delete_response.status_code, 200)
        self.assertTrue(
            ProductComponent.objects.filter(pk=foreign_component.pk).exists()
        )

    def test_user_without_permission_cannot_edit_or_see_edit_links(self):
        cashier = make_user(
            company=self.company,
            role="cashier",
            username="caixa-sem-edicao",
        )
        self.client.force_login(cashier)

        response = self.client.post(
            self.edit_url(),
            self.payload(name="Alteração indevida"),
        )

        self.assertRedirects(
            response,
            reverse("products:stock_dashboard"),
            fetch_redirect_response=False,
        )
        self.drink.refresh_from_db()
        self.assertEqual(self.drink.name, "Drink da casa")
        dashboard = self.client.get(reverse("products:stock_dashboard"))
        self.assertNotContains(dashboard, self.edit_url())

    def test_dashboard_links_authorized_user_to_product_editing(self):
        response = self.client.get(reverse("products:stock_dashboard"))

        self.assertContains(response, self.edit_url())
        self.assertContains(response, "Editar produto e receita")

    def test_removal_preserves_sale_snapshot_and_future_sales_use_new_recipe(self):
        order = Order.objects.create(
            company=self.company,
            status="pre_sale",
            created_by=self.user,
        )
        OrderItem.objects.create(
            order=order,
            company=self.company,
            product=self.drink,
            quantity=D("1"),
        )
        approval = approve_order(
            order_id=order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )
        sale_item = approval.sale.items.get()
        original_cost = sale_item.total_cost

        rows = self.component_rows()
        rows[1]["DELETE"] = "on"
        response = self.client.post(self.edit_url(), self.payload(rows=rows))
        self.assertEqual(response.status_code, 302)

        sale_item.refresh_from_db()
        lemon_snapshot = sale_item.component_snapshots.get(ingredient=self.lemon)
        self.assertIsNone(lemon_snapshot.source_component_id)
        self.assertEqual(lemon_snapshot.quantity_per_sale_unit, D("1"))
        self.assertEqual(sale_item.total_cost, original_cost)

        self.spirit_entry.refresh_from_db()
        self.lemon_entry.refresh_from_db()
        spirit_before = self.spirit_entry.remaining_quantity
        lemon_before = self.lemon_entry.remaining_quantity
        future_order = Order.objects.create(company=self.company, status="pre_sale")
        OrderItem.objects.create(
            order=future_order,
            company=self.company,
            product=self.drink,
            quantity=D("1"),
        )
        approve_order(
            order_id=future_order.pk,
            company=self.company,
            payment_method="pix",
            user=self.user,
        )
        self.spirit_entry.refresh_from_db()
        self.lemon_entry.refresh_from_db()
        self.assertEqual(self.spirit_entry.remaining_quantity, spirit_before - D("2"))
        self.assertEqual(self.lemon_entry.remaining_quantity, lemon_before)

        cancel_paid_order_with_stock_return(
            order_id=order.pk,
            company=self.company,
            user=self.user,
        )
        self.lemon_entry.refresh_from_db()
        self.assertEqual(self.lemon_entry.remaining_quantity, D("8"))

    def test_removal_preserves_production_consumption_and_new_production_uses_recipe(self):
        prepared = make_product(
            company=self.company,
            unit=self.unit,
            name="Porção pronta",
            inventory_role="prepared",
            preparation_mode="pre_portioned",
        )
        meat = make_product(
            company=self.company,
            unit=self.unit,
            name="Carne",
            product_type="internal_use",
            inventory_role="input",
        )
        package = make_product(
            company=self.company,
            unit=self.unit,
            name="Embalagem",
            product_type="internal_use",
            inventory_role="input",
        )
        meat_component = ProductComponent.objects.create(
            company=self.company,
            product=prepared,
            ingredient=meat,
            quantity=D("2"),
            unit="unit",
        )
        package_component = ProductComponent.objects.create(
            company=self.company,
            product=prepared,
            ingredient=package,
            quantity=D("1"),
            unit="unit",
        )
        make_entry(product=meat, quantity="30")
        make_entry(product=package, quantity="20")
        first = create_production(
            company=self.company,
            product=prepared,
            planned_quantity=D("2"),
            produced_quantity=D("2"),
            created_by=self.user,
        )

        rows = self.component_rows(prepared)
        rows[0]["quantity"] = "3"
        rows[1]["DELETE"] = "on"
        response = self.client.post(
            self.edit_url(prepared),
            self.payload(prepared, rows=rows),
        )
        self.assertEqual(response.status_code, 302)

        old_meat = first.production.consumptions.get(ingredient=meat)
        old_package = first.production.consumptions.get(ingredient=package)
        self.assertEqual(old_meat.quantity_per_planned_unit, D("2"))
        self.assertEqual(old_package.quantity_per_planned_unit, D("1"))
        self.assertIsNone(old_package.source_component_id)
        self.assertFalse(ProductComponent.objects.filter(pk=package_component.pk).exists())
        meat_component.refresh_from_db()
        self.assertEqual(meat_component.quantity, D("3"))

        second = create_production(
            company=self.company,
            product=prepared,
            planned_quantity=D("1"),
            produced_quantity=D("1"),
            created_by=self.user,
        )
        self.assertEqual(second.production.consumptions.count(), 1)
        new_meat = second.production.consumptions.get()
        self.assertEqual(new_meat.ingredient, meat)
        self.assertEqual(new_meat.theoretical_quantity, D("3"))
