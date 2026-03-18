from django.contrib.auth.models import AbstractUser
from django.db import models


class UserRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    ZEV_OWNER = "zev_owner", "ZEV Owner"
    PARTICIPANT = "participant", "Participant"
    GUEST = "guest", "Guest"


class User(AbstractUser):
    """Extended user model with role-based access control."""

    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.PARTICIPANT,
    )
    phone = models.CharField(max_length=30, blank=True)
    address_line1 = models.CharField(max_length=200, blank=True)
    address_line2 = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=10, blank=True)
    city = models.CharField(max_length=100, blank=True)
    must_change_password = models.BooleanField(default=False)

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN or self.is_superuser

    @property
    def is_zev_owner(self):
        return self.role in (UserRole.ADMIN, UserRole.ZEV_OWNER) or self.is_superuser

    def __str__(self):
        return f"{self.get_full_name() or self.username} <{self.email}>"


class AppSettings(models.Model):
    SHORT_DATE_DD_MM_YYYY = "dd.MM.yyyy"
    SHORT_DATE_DD_SLASH_MM_SLASH_YYYY = "dd/MM/yyyy"
    SHORT_DATE_MM_SLASH_DD_SLASH_YYYY = "MM/dd/yyyy"
    SHORT_DATE_YYYY_MM_DD = "yyyy-MM-dd"

    LONG_DATE_D_MMMM_YYYY = "d MMMM yyyy"
    LONG_DATE_D_DOT_MMMM_YYYY = "d. MMMM yyyy"
    LONG_DATE_MMMM_D_YYYY = "MMMM d, yyyy"
    LONG_DATE_YYYY_MM_DD = "yyyy-MM-dd"

    DATETIME_DD_MM_YYYY_HH_MM = "dd.MM.yyyy HH:mm"
    DATETIME_DD_SLASH_MM_SLASH_YYYY_HH_MM = "dd/MM/yyyy HH:mm"
    DATETIME_MM_SLASH_DD_SLASH_YYYY_HH_MM = "MM/dd/yyyy HH:mm"
    DATETIME_YYYY_MM_DD_HH_MM = "yyyy-MM-dd HH:mm"

    SHORT_DATE_FORMAT_CHOICES = [
        (SHORT_DATE_DD_MM_YYYY, "DD.MM.YYYY"),
        (SHORT_DATE_DD_SLASH_MM_SLASH_YYYY, "DD/MM/YYYY"),
        (SHORT_DATE_MM_SLASH_DD_SLASH_YYYY, "MM/DD/YYYY"),
        (SHORT_DATE_YYYY_MM_DD, "YYYY-MM-DD"),
    ]
    LONG_DATE_FORMAT_CHOICES = [
        (LONG_DATE_D_MMMM_YYYY, "D MMMM YYYY"),
        (LONG_DATE_D_DOT_MMMM_YYYY, "D. MMMM YYYY"),
        (LONG_DATE_MMMM_D_YYYY, "MMMM D, YYYY"),
        (LONG_DATE_YYYY_MM_DD, "YYYY-MM-DD"),
    ]
    DATETIME_FORMAT_CHOICES = [
        (DATETIME_DD_MM_YYYY_HH_MM, "DD.MM.YYYY HH:mm"),
        (DATETIME_DD_SLASH_MM_SLASH_YYYY_HH_MM, "DD/MM/YYYY HH:mm"),
        (DATETIME_MM_SLASH_DD_SLASH_YYYY_HH_MM, "MM/DD/YYYY HH:mm"),
        (DATETIME_YYYY_MM_DD_HH_MM, "YYYY-MM-DD HH:mm"),
    ]

    singleton_enforcer = models.BooleanField(default=True, unique=True, editable=False)
    date_format_short = models.CharField(
        max_length=20,
        choices=SHORT_DATE_FORMAT_CHOICES,
        default=SHORT_DATE_DD_MM_YYYY,
    )
    date_format_long = models.CharField(
        max_length=20,
        choices=LONG_DATE_FORMAT_CHOICES,
        default=LONG_DATE_D_MMMM_YYYY,
    )
    date_time_format = models.CharField(
        max_length=25,
        choices=DATETIME_FORMAT_CHOICES,
        default=DATETIME_DD_MM_YYYY_HH_MM,
    )
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        self.singleton_enforcer = True
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "singleton_enforcer": True,
                "date_format_short": cls.SHORT_DATE_DD_MM_YYYY,
                "date_format_long": cls.LONG_DATE_D_MMMM_YYYY,
                "date_time_format": cls.DATETIME_DD_MM_YYYY_HH_MM,
            },
        )
        return obj

    def __str__(self):
        return "Application settings"
