from django.urls import path
from . import views
from . import api

app_name = "printing"

urlpatterns = [
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
