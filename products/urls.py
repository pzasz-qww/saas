from django.urls import path

from . import views

app_name = "products"

urlpatterns = [
    path("estoque/", views.stock_dashboard, name="stock_dashboard"),
    path("estoque/lista-compras/", views.shopping_list, name="shopping_list"),
    path("estoque/relatorio/pdf/", views.stock_report_pdf, name="stock_report_pdf"),
    path("estoque/entrada/", views.stock_entry_create, name="stock_entry_create"),
    path("estoque/conferencia/", views.stock_count_adjust, name="stock_count_adjust"),
    path("estoque/producoes/", views.production_list, name="production_list"),
    path(
        "estoque/produzir/<int:product_id>/",
        views.production_create,
        name="production_create",
    ),
    path(
        "estoque/producoes/<int:production_id>/",
        views.production_detail,
        name="production_detail",
    ),
    path(
        "estoque/producoes/<int:production_id>/reverter/",
        views.production_reverse,
        name="production_reverse",
    ),
    path("produtos/novo/", views.product_create, name="product_create"),
]
