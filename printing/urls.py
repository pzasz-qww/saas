from django.urls import path
from . import views
from . import api
from . import connector

app_name = "printing"

urlpatterns = [
    path("connector/installer/", connector.installer, name="connector_installer"),
    path("connector/download/", connector.download_link, name="connector_download"),
    path("api/v1/connector/exchange/", connector.exchange, name="connector_exchange"),
    path("api/v1/connector/configure/", connector.configure, name="connector_configure"),
    path("api/v1/connector/status/", connector.status, name="connector_status"),
    path("jobs/", views.jobs_view, name="jobs"),
    path("jobs/<int:job_id>/preview/", views.preview_view, name="preview"),
    path("jobs/<int:job_id>/reprint/", views.reprint_view, name="reprint"),
    path("jobs/<int:job_id>/uncertain/", views.uncertain_view, name="uncertain"),
    path("api/v1/jobs/claim/", api.next_job, name="bridge_claim"),
    path("api/v1/jobs/<int:job_id>/result/", api.result, name="bridge_result"),
    path(
        "settings/",
        views.settings_view,
        name="settings"
    ),
]
