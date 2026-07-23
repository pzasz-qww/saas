from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def settings_view(request):
    return render(
        request,
        "printing/settings.html"
    )
