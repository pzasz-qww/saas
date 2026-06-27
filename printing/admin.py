
from django.contrib import admin
from .models import Printer, PrintSettings, PrintJob

admin.site.register(Printer)
admin.site.register(PrintSettings)
admin.site.register(PrintJob)