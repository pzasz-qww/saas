from django.db import models
from django.contrib.auth.models import User

from companies.models import Company


PERMISSION_FIELDS = [
    "can_access_pdv",
    "can_create_order",
    "can_approve_order",
    "can_mark_delivered",
    "can_cancel_pre_sale",
    "can_cancel_paid_order",
    "can_discard_paid_order",
    "can_view_orders_panel",
    "can_view_stock",
    "can_view_reports",
    "can_create_stock_entry",
    "can_adjust_stock",
    "can_manage_users",
]


class StaffRole(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    name = models.CharField(
        max_length=80,
        help_text="Ex: Garçom, Caixa, Gerente, Estoque, Freela sábado.",
    )

    can_access_pdv = models.BooleanField(default=False)
    can_create_order = models.BooleanField(default=False)
    can_approve_order = models.BooleanField(default=False)
    can_mark_delivered = models.BooleanField(default=False)

    can_cancel_pre_sale = models.BooleanField(default=False)
    can_cancel_paid_order = models.BooleanField(default=False)
    can_discard_paid_order = models.BooleanField(default=False)

    can_view_orders_panel = models.BooleanField(default=False)
    can_view_stock = models.BooleanField(default=False)
    can_view_reports = models.BooleanField(default=False)

    can_create_stock_entry = models.BooleanField(default=False)
    can_adjust_stock = models.BooleanField(default=False)

    can_manage_users = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Função"
        verbose_name_plural = "Funções"
        ordering = ["name"]
        unique_together = ("company", "name")

    def apply_to_profile(self, profile):
        for field in PERMISSION_FIELDS:
            setattr(profile, field, getattr(self, field))

    def __str__(self):
        return f"{self.name} - {self.company.name}"


class Profile(models.Model):
    ROLE_CHOICES = [
        ("owner", "Dono"),
        ("manager", "Gerente"),
        ("cashier", "Caixa"),
        ("waiter", "Garçom"),
        ("stock", "Estoque"),
        ("kitchen", "Cozinha"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="waiter",
    )

    role_template = models.ForeignKey(
        StaffRole,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="profiles",
        verbose_name="Função personalizada",
    )

    can_access_pdv = models.BooleanField(default=False)
    can_create_order = models.BooleanField(default=False)
    can_approve_order = models.BooleanField(default=False)
    can_mark_delivered = models.BooleanField(default=False)

    can_cancel_pre_sale = models.BooleanField(default=False)
    can_cancel_paid_order = models.BooleanField(default=False)
    can_discard_paid_order = models.BooleanField(default=False)

    can_view_orders_panel = models.BooleanField(default=False)
    can_view_stock = models.BooleanField(default=False)
    can_view_reports = models.BooleanField(default=False)

    can_create_stock_entry = models.BooleanField(default=False)
    can_adjust_stock = models.BooleanField(default=False)

    can_manage_users = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Perfil"
        verbose_name_plural = "Perfis"

    def apply_legacy_role_defaults(self):
        defaults = {
            "owner": {
                "can_access_pdv": True,
                "can_create_order": True,
                "can_approve_order": True,
                "can_mark_delivered": True,
                "can_cancel_pre_sale": True,
                "can_cancel_paid_order": True,
                "can_discard_paid_order": True,
                "can_view_orders_panel": True,
                "can_view_stock": True,
                "can_view_reports": True,
                "can_create_stock_entry": True,
                "can_adjust_stock": True,
                "can_manage_users": True,
            },
            "manager": {
                "can_access_pdv": True,
                "can_create_order": True,
                "can_approve_order": True,
                "can_mark_delivered": True,
                "can_cancel_pre_sale": True,
                "can_cancel_paid_order": True,
                "can_discard_paid_order": True,
                "can_view_orders_panel": True,
                "can_view_stock": True,
                "can_view_reports": True,
                "can_create_stock_entry": True,
                "can_adjust_stock": True,
                "can_manage_users": False,
            },
            "cashier": {
                "can_access_pdv": True,
                "can_create_order": True,
                "can_approve_order": True,
                "can_mark_delivered": True,
                "can_cancel_pre_sale": True,
                "can_cancel_paid_order": False,
                "can_discard_paid_order": False,
                "can_view_orders_panel": True,
                "can_view_stock": True,
                "can_view_reports": False,
                "can_create_stock_entry": False,
                "can_adjust_stock": False,
                "can_manage_users": False,
            },
            "waiter": {
                "can_access_pdv": True,
                "can_create_order": True,
                "can_approve_order": False,
                "can_mark_delivered": False,
                "can_cancel_pre_sale": False,
                "can_cancel_paid_order": False,
                "can_discard_paid_order": False,
                "can_view_orders_panel": False,
                "can_view_stock": False,
                "can_view_reports": False,
                "can_create_stock_entry": False,
                "can_adjust_stock": False,
                "can_manage_users": False,
            },
            "stock": {
                "can_access_pdv": False,
                "can_create_order": False,
                "can_approve_order": False,
                "can_mark_delivered": False,
                "can_cancel_pre_sale": False,
                "can_cancel_paid_order": False,
                "can_discard_paid_order": False,
                "can_view_orders_panel": False,
                "can_view_stock": True,
                "can_view_reports": False,
                "can_create_stock_entry": True,
                "can_adjust_stock": True,
                "can_manage_users": False,
            },
            "kitchen": {
                "can_access_pdv": False,
                "can_create_order": False,
                "can_approve_order": False,
                "can_mark_delivered": True,
                "can_cancel_pre_sale": False,
                "can_cancel_paid_order": False,
                "can_discard_paid_order": False,
                "can_view_orders_panel": True,
                "can_view_stock": False,
                "can_view_reports": False,
                "can_create_stock_entry": False,
                "can_adjust_stock": False,
                "can_manage_users": False,
            },
        }

        role_defaults = defaults.get(self.role, {})

        for permission_name, value in role_defaults.items():
            setattr(self, permission_name, value)

    def apply_role_defaults(self):
        if self.role_template:
            self.role_template.apply_to_profile(self)
        else:
            self.apply_legacy_role_defaults()

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        if is_new:
            self.apply_role_defaults()

        super().save(*args, **kwargs)

    def role_name(self):
        if self.role_template:
            return self.role_template.name

        return self.get_role_display()

    def __str__(self):
        return f"{self.user.username} - {self.company.name} - {self.role_name()}"