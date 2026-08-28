from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from django.views.generic import RedirectView


def global_admin_has_permission(request):
    return request.user.is_active and request.user.is_superuser


admin.site.site_header = "Bar SaaS — Administração global (todas as empresas)"
admin.site.site_title = "Administração global"
admin.site.index_title = "Acesso restrito a superusuários"
admin.site.has_permission = global_admin_has_permission

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

if settings.IS_PORTABLE:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {
                "document_root": settings.MEDIA_ROOT,
                "show_indexes": False,
            },
        ),
    ]
