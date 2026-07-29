import logging

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from common.models.base import UUIDModel

logger = logging.getLogger(__name__)


class ProviderUserManager(UserManager):
    """Custom manager so that superusers are always providers."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_provider", True)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser, UUIDModel):
    """
    Custom User model extending Django's AbstractUser.
    Inherits from UUIDModel to use UUIDv4 as primary key instead of auto-incrementing integer.
    """

    objects = ProviderUserManager()  # type: ignore[misc]

    phone = models.CharField(max_length=20, blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    is_provider = models.BooleanField(
        default=False,
        help_text="Designates whether the user is a medical provider with dashboard access.",
    )

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self) -> str:
        return f"User({self.username})"
