from django.shortcuts import render

def settings_view(request):
    return render(
        request,
        "printing/settings.html"
    )