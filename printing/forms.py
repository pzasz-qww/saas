from django import forms

from .models import Printer, PrintSettings


class PrinterForm(forms.ModelForm):
    class Meta:
        model = Printer
        fields = ["name", "active", "paper_width", "characters_per_line", "auto_cut"]


class PrintSettingsForm(forms.ModelForm):
    class Meta:
        model = PrintSettings
        fields = ["default_printer", "automatic", "timezone_name"]
        labels = {"default_printer": "Impressora padrão"}

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_printer"].queryset = Printer.objects.filter(company=company)
