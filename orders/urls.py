from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("pdv/", views.pdv_view, name="pdv"),
    path("pedidos/", views.orders_panel, name="orders_panel"),

    path(
        "pedidos/<int:order_id>/",
        views.order_detail,
        name="order_detail",
    ),

    path(
        "pedidos/<int:order_id>/aprovar/<str:payment_method>/",
        views.approve_order,
        name="approve_order",
    ),

    path(
        "pedidos/<int:order_id>/entregar/",
        views.mark_order_delivered,
        name="mark_order_delivered",
    ),

    path(
        "pedidos/<int:order_id>/cancelar/",
        views.cancel_order,
        name="cancel_order",
    ),

    path(
        "pedidos/<int:order_id>/cancelar-com-retorno/",
        views.cancel_paid_order_with_stock_return,
        name="cancel_paid_order_with_stock_return",
    ),

    path(
        "pedidos/<int:order_id>/descartar/",
        views.discard_paid_order,
        name="discard_paid_order",
    ),
]