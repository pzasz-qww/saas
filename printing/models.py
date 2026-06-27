from django.db import models


class Printer(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class PrintSettings(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)


class PrintJob(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)