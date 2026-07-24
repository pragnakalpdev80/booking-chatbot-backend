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
    def test_create_booking_with_email(self, admin_user):
        """Booking is created with email, no user FK required."""
        booking = Booking.objects.create(
            email="user@example.com",
            provider=admin_user,
            name="Jane Doe",
            google_event_id="evt_001",
            start_time=datetime.datetime(2026, 8, 1, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 1, 10, 30, tzinfo=datetime.UTC),
            reason="Test booking",
        )
        assert booking.pk is not None
        assert booking.email == "user@example.com"
        assert booking.status == BookingStatus.CONFIRMED

    def test_multiple_bookings_same_email_allowed(self, admin_user):
        """Multiple bookings per email are permitted."""
        for i in range(3):
            Booking.objects.create(
                email="multi@example.com",
                provider=admin_user,
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

    def test_booking_status_default_confirmed(self, admin_user):
        booking = Booking.objects.create(
            email="status@example.com",
            provider=admin_user,
            google_event_id="evt_status",
            start_time=datetime.datetime(2026, 8, 1, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 1, 10, 30, tzinfo=datetime.UTC),
        )
        assert booking.status == BookingStatus.CONFIRMED

    def test_google_event_id_is_unique(self, admin_user):
        """Two bookings cannot share the same Google event ID."""
        from django.db import IntegrityError

        Booking.objects.create(
            email="a@example.com",
            provider=admin_user,
            google_event_id="unique_evt",
            start_time=datetime.datetime(2026, 8, 1, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 1, 10, 30, tzinfo=datetime.UTC),
        )

        duplicate = Booking(
            email="b@example.com",
            provider=admin_user,
            google_event_id="unique_evt",
            start_time=datetime.datetime(2026, 8, 2, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 2, 10, 30, tzinfo=datetime.UTC),
        )
        with pytest.raises(IntegrityError):
            duplicate.save()


@pytest.mark.django_db
class TestProviderSettingsModel:
    def test_get_for_provider_creates_default(self, admin_user):
        ps = ProviderSettings.get_for_provider(admin_user)
        assert ps.user == admin_user
        assert ps.slot_duration == 30
        assert ps.work_days == [0, 1, 2, 3, 4]
        assert ps.calendar_id == "primary"


@pytest.mark.django_db
class TestEncryptionHelpers:
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = '{"token": "abc123"}'
        ciphertext = encrypt_token(plaintext)
        assert ciphertext != plaintext
        assert decrypt_token(ciphertext) == plaintext
