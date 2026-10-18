import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class ImmutableQuerySet(models.QuerySet):
    def protected_fields(self):
        return set(self.model.immutable_fields) | {
            field.name for field in self.model._meta.concrete_fields
            if field.attname in self.model.immutable_fields
        }

    def update(self, **kwargs):
        if set(kwargs) & self.protected_fields():
            raise ValidationError("O snapshot e sua origem não podem ser alterados.")
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        if set(fields) & self.protected_fields():
            raise ValidationError("O snapshot e sua origem não podem ser alterados.")
        return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, batch_size=None, ignore_conflicts=False, update_conflicts=False, update_fields=None, unique_fields=None):
        if update_conflicts and set(update_fields or ()) & self.protected_fields():
            raise ValidationError("O snapshot e sua origem não podem ser alterados.")
        return super().bulk_create(objs, batch_size=batch_size, ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts, update_fields=update_fields, unique_fields=unique_fields)


class ImmutableRecord(models.Model):
    objects = ImmutableQuerySet.as_manager()
    immutable_fields = ()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            original = type(self).objects.using(kwargs.get("using") or self._state.db).get(pk=self.pk)
            if any(getattr(original, f) != getattr(self, f) for f in self.immutable_fields):
                raise ValidationError("O snapshot e sua origem não podem ser alterados.")
        self.clean()
        return super().save(*args, **kwargs)


class Printer(models.Model):
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT)
    name = models.CharField("Nome", max_length=100)
    identifier = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    active = models.BooleanField("Ativa", default=True)
    paper_width = models.PositiveSmallIntegerField("Largura (mm)", default=80,
        validators=[MinValueValidator(58), MaxValueValidator(112)])
    characters_per_line = models.PositiveSmallIntegerField("Caracteres por linha", default=48,
        validators=[MinValueValidator(32), MaxValueValidator(64)])
    auto_cut = models.BooleanField("Corte automático", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(characters_per_line__gte=32, characters_per_line__lte=64), name="printing_columns_range"),
            models.CheckConstraint(condition=models.Q(paper_width__gte=58, paper_width__lte=112), name="printing_width_range"),
        ]

    def __str__(self):
        return self.name


class PrintSettings(models.Model):
    company = models.OneToOneField("companies.Company", on_delete=models.PROTECT)
    default_printer = models.ForeignKey(Printer, on_delete=models.PROTECT, null=True, blank=True)
    automatic = models.BooleanField("Imprimir vendas automaticamente", default=False)
    timezone_name = models.CharField("Fuso horário do ticket", max_length=64, default="America/Sao_Paulo")
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        if self.default_printer_id and self.default_printer.company_id != self.company_id:
            raise ValidationError("A impressora precisa pertencer à mesma empresa.")
        if self.automatic and not self.default_printer_id:
            raise ValidationError("Selecione uma impressora para ativar a impressão automática.")
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError({"timezone_name": "Fuso horário inválido."}) from None

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class OrderPrintContext(ImmutableRecord):
    """Identity captured at order creation; never guesses a legacy employee role."""
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT)
    order_reference = models.PositiveBigIntegerField()
    employee_name = models.CharField(max_length=300)
    employee_role = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    immutable_fields = ("company_id", "order_reference", "employee_name", "employee_role")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "order_reference"], name="printing_order_context_unique")]


class ItemPrintContext(ImmutableRecord):
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT)
    item_reference = models.PositiveBigIntegerField()
    product_reference = models.PositiveBigIntegerField()
    order_reference = models.PositiveBigIntegerField()
    product_name = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)
    immutable_fields = ("company_id", "item_reference", "product_reference", "order_reference", "product_name")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["company", "item_reference", "product_reference"], name="printing_item_context_unique")]


class BridgeCredential(models.Model):
    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT)
    printer = models.ForeignKey(Printer, on_delete=models.PROTECT)
    identifier = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    secret_hash = models.CharField(max_length=128, editable=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.printer_id and self.printer.company_id != self.company_id:
            raise ValidationError("A credencial e a impressora precisam pertencer à mesma empresa.")

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class ConnectorLink(models.Model):
    company = models.ForeignKey("companies.Company", on_delete=models.CASCADE)
    digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


class PrintJob(ImmutableRecord):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PROCESSING = "processing", "Imprimindo"
        PRINTED = "printed", "Impresso"
        ERROR = "error", "Erro"

    company = models.ForeignKey("companies.Company", on_delete=models.PROTECT)
    printer = models.ForeignKey(Printer, on_delete=models.PROTECT)
    order_reference = models.PositiveBigIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    printed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    reprint_of = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="reprints")
    event_key = models.CharField(max_length=120, null=True, blank=True)
    claimed_by = models.ForeignKey(BridgeCredential, on_delete=models.PROTECT, null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    immutable_fields = ("company_id", "printer_id", "order_reference", "payload", "event_key", "reprint_of_id")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["company", "event_key"], condition=models.Q(event_key__isnull=False), name="printing_event_unique"),
            models.CheckConstraint(condition=models.Q(status__in=["pending", "processing", "printed", "error"]), name="printing_status_valid"),
        ]
        indexes = [models.Index(fields=["company", "printer", "status", "id"], name="printing_queue_idx")]

    def clean(self):
        if self.printer_id and self.printer.company_id != self.company_id:
            raise ValidationError("O trabalho e a impressora precisam pertencer à mesma empresa.")
        if self.reprint_of_id and self.reprint_of.company_id != self.company_id:
            raise ValidationError("A reimpressão precisa pertencer à mesma empresa.")
        if self.claimed_by_id and (self.claimed_by.company_id != self.company_id or self.claimed_by.printer_id != self.printer_id):
            raise ValidationError("Credencial incompatível com o trabalho.")
