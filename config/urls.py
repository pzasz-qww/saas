from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
urlpatterns = [
    path(
        "",
        RedirectView.as_view(
            url="/accounts/login/",
            permanent=False
        ),
    ),

    path("admin/", admin.site.urls),

    path("", include("accounts.urls")),
    path("", include("products.urls")),
    path("", include("orders.urls")),

    path(
        "printing/",
        include("printing.urls")
    ),
]