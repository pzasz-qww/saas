from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("pessoal/", views.people_management, name="people_management"),
    path(
        "support/companies/",
        views.support_companies,
        name="support_companies",
    ),
    path(
        "support/companies/<int:company_id>/select/",
        views.select_support_company,
        name="select_support_company",
    ),
    path(
        "support/companies/clear/",
        views.clear_support_company,
        name="clear_support_company",
    ),
]
