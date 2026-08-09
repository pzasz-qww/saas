from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.permissions import company_required


@login_required
@company_required
def settings_view(request):
    return render(
        request,
        "printing/settings.html"
    )
