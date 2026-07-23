# apps/calendar_app/tests/test_models.py
"""
Unit tests for calendar_app models.
Verifies anonymous email-based Booking creation and ProviderSettings singleton.
"""

import datetime

import pytest

from apps.calendar_app.models import (
    Booking,
    BookingStatus,
    ProviderSettings,
    decrypt_token,
    encrypt_token,
)


@pytest.mark.django_db
class TestBookingModel:
    def test_create_booking_with_email(self):
        """Booking is created with email, no user FK required."""
        booking = Booking.objects.create(
            email="user@example.com",
            name="Jane Doe",
            google_event_id="evt_001",
            start_time=datetime.datetime(2026, 8, 1, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 1, 10, 30, tzinfo=datetime.UTC),
            reason="Test booking",
        )
        assert booking.pk is not None
        assert booking.email == "user@example.com"
        assert booking.status == BookingStatus.CONFIRMED

    def test_multiple_bookings_same_email_allowed(self):
        """Multiple bookings per email are permitted."""
        for i in range(3):
            Booking.objects.create(
                email="multi@example.com",
                google_event_id=f"evt_{i}",
                start_time=datetime.datetime(2026, 8, i + 1, 10, 0, tzinfo=datetime.UTC),
                end_time=datetime.datetime(2026, 8, i + 1, 10, 30, tzinfo=datetime.UTC),
            )
        assert Booking.objects.filter(email="multi@example.com").count() == 3

    def test_booking_str(self):
        booking = Booking(
            email="str@example.com",
            google_event_id="evt_str",
            start_time=datetime.datetime(2026, 8, 1, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 1, 10, 30, tzinfo=datetime.UTC),
        )
        assert "str@example.com" in str(booking)
        assert "evt_str" in str(booking)

    def test_booking_status_default_confirmed(self):
        booking = Booking.objects.create(
            email="status@example.com",
            google_event_id="evt_status",
            start_time=datetime.datetime(2026, 8, 1, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 1, 10, 30, tzinfo=datetime.UTC),
        )
        assert booking.status == BookingStatus.CONFIRMED

    def test_google_event_id_is_unique(self):
        """Two bookings cannot share the same Google event ID."""
        from django.db import IntegrityError

        Booking.objects.create(
            email="a@example.com",
            google_event_id="unique_evt",
            start_time=datetime.datetime(2026, 8, 1, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 1, 10, 30, tzinfo=datetime.UTC),
        )
        with pytest.raises(IntegrityError):
            Booking.objects.create(
                email="b@example.com",
                google_event_id="unique_evt",
                start_time=datetime.datetime(2026, 8, 2, 10, 0, tzinfo=datetime.UTC),
                end_time=datetime.datetime(2026, 8, 2, 10, 30, tzinfo=datetime.UTC),
            )


@pytest.mark.django_db
class TestProviderSettingsModel:
    def test_get_instance_creates_default(self):
        ps = ProviderSettings.get_instance()
        assert ps.pk == 1
        assert ps.slot_duration == 30
        assert ps.work_days == [0, 1, 2, 3, 4]

    def test_singleton_enforcement(self):
        from django.core.exceptions import ValidationError

        ProviderSettings.get_instance()
        new_ps = ProviderSettings(provider_name="Second")
        with pytest.raises(ValidationError):
            new_ps.clean()


@pytest.mark.django_db
class TestEncryptionHelpers:
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = '{"token": "abc123"}'
        ciphertext = encrypt_token(plaintext)
        assert ciphertext != plaintext
        assert decrypt_token(ciphertext) == plaintext
