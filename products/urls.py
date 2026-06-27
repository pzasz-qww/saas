from django.urls import path

from . import views

app_name = "products"

urlpatterns = [
    path("estoque/", views.stock_dashboard, name="stock_dashboard"),
    path("estoque/entrada/", views.stock_entry_create, name="stock_entry_create"),
    path("estoque/conferencia/", views.stock_count_adjust, name="stock_count_adjust"),
    path("produtos/novo/", views.product_create, name="product_create"),
]