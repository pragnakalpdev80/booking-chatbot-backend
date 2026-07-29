"""Abstract model bases reused by every concrete model.

Concrete models inherit :class:`UUIDModel` (UUID PK + timestamps) in almost all
cases; the two mixins are provided separately for the rare model that needs only
one behavior.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _


class UUIDPrimaryKeyModel(models.Model):
    """Adds a non-sequential UUID primary key (avoids enumerable integer IDs)."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("ID"),
    )

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    """Adds self-managing ``created_at`` / ``updated_at`` audit timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("created at"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("updated at"))

    class Meta:
        abstract = True


class UUIDModel(UUIDPrimaryKeyModel, TimeStampedModel):
    """Canonical base: UUID primary key plus audit timestamps."""

    class Meta:
        abstract = True
