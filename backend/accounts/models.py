from datetime import date, timedelta

from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class UserRole(models.TextChoices):
    ADMIN = "admin", "Admin"
    ZEV_OWNER = "zev_owner", "ZEV Owner"
    PARTICIPANT = "participant", "Participant"
    GUEST = "guest", "Guest"


class OpenZevUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # Keep Django superuser flags and OpenZEV role in sync.
        extra_fields.setdefault("role", UserRole.ADMIN)
        if extra_fields.get("role") != UserRole.ADMIN:
            raise ValueError("Superuser must have role='admin'.")
        return super().create_superuser(username, email=email, password=password, **extra_fields)


class User(AbstractUser):
    """Extended user model with role-based access control."""

    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.PARTICIPANT,
    )
    must_change_password = models.BooleanField(default=False)
    objects = OpenZevUserManager()

    @property
    def is_admin(self):
        return self.role == UserRole.ADMIN or self.is_superuser

    @property
    def is_zev_owner(self):
        return self.role in (UserRole.ADMIN, UserRole.ZEV_OWNER) or self.is_superuser

    def __str__(self):
        return f"{self.get_full_name() or self.username} <{self.email}>"


class EmailVerificationToken(models.Model):
    """One-time email verification token for self-registered accounts."""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='email_verification_tokens',
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def is_valid(self) -> bool:
        if self.consumed_at:
            return False
        return timezone.now() < self.created_at + timedelta(hours=24)


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


class VatRate(models.Model):
    rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="VAT rate as decimal fraction (e.g. 0.0810 for 8.10%).",
    )
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-valid_from", "-created_at"]

    def clean(self):
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError({"valid_to": "valid_to must be on or after valid_from."})

        candidate_end = self.valid_to or date.max
        overlap_exists = VatRate.objects.exclude(pk=self.pk).filter(
            valid_from__lte=candidate_end,
        ).filter(
            models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=self.valid_from),
        ).exists()
        if overlap_exists:
            raise ValidationError(
                "VAT rate ranges must not overlap. Adjust valid_from/valid_to so only one rate is active per day."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def active_for_day(cls, day: date):
        return cls.objects.filter(
            valid_from__lte=day,
        ).filter(
            models.Q(valid_to__isnull=True) | models.Q(valid_to__gte=day)
        ).order_by("-valid_from", "-created_at").first()

    def __str__(self):
        valid_to = self.valid_to.isoformat() if self.valid_to else "open"
        return f"VAT {self.rate} ({self.valid_from} - {valid_to})"
