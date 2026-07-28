# calendar_app/tests/test_reconcile.py
"""
Tests for the reconcile_bookings_with_gcal task and invalidate_freebusy_cache helper.

Follows CLAUDE.md §6 Testing Rules:
  - At least one happy-path and one error-path test per unit of behaviour.
  - All Google API calls are mocked with unittest.mock.
  - Fixtures mirror the pattern established in test_tasks.py.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.utils.timezone import now
from googleapiclient.errors import HttpError

from apps.calendar_app.models import (
    Booking,
    BookingStatus,
    GoogleCredential,
    ProviderSettings,
)
from apps.calendar_app.tasks import invalidate_freebusy_cache, reconcile_bookings_with_gcal

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def provider_with_cred(db, user):
    """Create a provider user with Google credential and provider settings."""
    ProviderSettings.objects.get_or_create(user=user, defaults={"payment_required": False})
    cred = GoogleCredential(user=user)
    cred.set_token(
        '{"token": "tok", "refresh_token": "rt", "client_id": "ci", "client_secret": "cs", "token_uri": "u"}'  # noqa: E501
    )
    cred.save()
    return user


@pytest.fixture
def confirmed_booking(db, provider_with_cred):
    """A CONFIRMED booking 2 days in the future."""
    start = now() + timedelta(days=2)
    return Booking.objects.create(
        provider=provider_with_cred,
        email="patient@example.com",
        start_time=start,
        end_time=start + timedelta(minutes=30),
        google_event_id="gcal_event_abc",
        status=BookingStatus.CONFIRMED,
    )


# ─── invalidate_freebusy_cache ────────────────────────────────────────────────


@pytest.mark.django_db
class TestInvalidateFreebusyCache:
    def test_deletes_existing_cache_key(self):
        """Should remove a cached freebusy result from Redis/LocMemCache."""
        cache_key = "freebusy_1_primary_2024-01-15"
        busy = [{"start": "2024-01-15T10:00:00Z", "end": "2024-01-15T10:30:00Z"}]
        cache.set(cache_key, busy, 120)

        invalidate_freebusy_cache(provider_id=1, calendar_id="primary", target_date="2024-01-15")

        assert cache.get(cache_key) is None

    def test_non_existent_key_does_not_raise(self):
        """Deleting a key that doesn't exist must be a no-op (not raise)."""
        # Should not raise
        invalidate_freebusy_cache(provider_id=99, calendar_id="primary", target_date="2024-01-01")


# ─── reconcile_bookings_with_gcal ─────────────────────────────────────────────


@pytest.mark.django_db
class TestReconcileTask:
    @patch("apps.calendar_app.tasks._get_service")
    def test_event_deleted_cancels_booking(self, mock_get_service, confirmed_booking):
        """If Google returns 404, the booking must be CANCELLED in the DB."""
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service

        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_service.events().get().execute.side_effect = HttpError(mock_resp, b"Not Found")

        reconcile_bookings_with_gcal()

        confirmed_booking.refresh_from_db()
        assert confirmed_booking.status == BookingStatus.CANCELLED

    @patch("apps.calendar_app.tasks._get_service")
    def test_event_deleted_invalidates_cache(self, mock_get_service, confirmed_booking):
        """Cancelling a booking due to 404 must also clear the freebusy cache."""
        target_date = confirmed_booking.start_time.date().isoformat()
        ps = ProviderSettings.get_for_provider(confirmed_booking.provider)
        cache_key = f"freebusy_{confirmed_booking.provider_id}_{ps.calendar_id}_{target_date}"
        cache.set(cache_key, [], 120)

        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_service.events().get().execute.side_effect = HttpError(mock_resp, b"Not Found")

        reconcile_bookings_with_gcal()

        assert cache.get(cache_key) is None

    @patch("apps.calendar_app.tasks._get_service")
    def test_time_drift_updates_db(self, mock_get_service, confirmed_booking):
        """If Google event time differs from DB, the DB must be updated to match Google."""
        new_start = confirmed_booking.start_time + timedelta(hours=1)
        new_end = confirmed_booking.end_time + timedelta(hours=1)

        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().get().execute.return_value = {
            "start": {"dateTime": new_start.isoformat()},
            "end": {"dateTime": new_end.isoformat()},
        }

        reconcile_bookings_with_gcal()

        confirmed_booking.refresh_from_db()
        # Compare to the second — timezone-aware comparison
        assert abs((confirmed_booking.start_time - new_start).total_seconds()) < 1
        assert abs((confirmed_booking.end_time - new_end).total_seconds()) < 1

    @patch("apps.calendar_app.tasks._get_service")
    def test_matching_times_no_update(self, mock_get_service, confirmed_booking):
        """If Google event time matches DB exactly, the booking must NOT be modified."""
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_service.events().get().execute.return_value = {
            "start": {"dateTime": confirmed_booking.start_time.isoformat()},
            "end": {"dateTime": confirmed_booking.end_time.isoformat()},
        }

        original_updated_at = confirmed_booking.updated_at
        reconcile_bookings_with_gcal()

        confirmed_booking.refresh_from_db()
        assert confirmed_booking.updated_at == original_updated_at
        assert confirmed_booking.status == BookingStatus.CONFIRMED

    @patch("apps.calendar_app.tasks._get_service")
    def test_non_404_http_error_skips_booking(self, mock_get_service, confirmed_booking):
        """A 500 error from Google must skip the booking (do not cancel) and not raise."""
        mock_service = MagicMock()
        mock_get_service.return_value = mock_service
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_service.events().get().execute.side_effect = HttpError(mock_resp, b"Server Error")

        reconcile_bookings_with_gcal()  # Must not raise

        confirmed_booking.refresh_from_db()
        assert confirmed_booking.status == BookingStatus.CONFIRMED  # Unchanged

    @patch("apps.calendar_app.tasks._get_service")
    def test_no_bookings_runs_cleanly(self, mock_get_service, db):
        """Task must complete without error when there are no upcoming confirmed bookings."""
        mock_get_service.return_value = MagicMock()
        reconcile_bookings_with_gcal()  # Must not raise
        mock_get_service.assert_not_called()  # No bookings → no API calls

    @patch("apps.calendar_app.tasks._get_service")
    def test_runtime_error_skips_booking(self, mock_get_service, confirmed_booking):
        """If the Google credential is missing (RuntimeError), skip the booking gracefully."""
        mock_get_service.side_effect = RuntimeError("No credential")

        reconcile_bookings_with_gcal()  # Must not raise

        confirmed_booking.refresh_from_db()
        assert confirmed_booking.status == BookingStatus.CONFIRMED  # Unchanged
