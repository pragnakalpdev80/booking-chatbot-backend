# apps/calendar_app/tests/test_api.py
"""
API tests for anonymous calendar_app endpoints.
All booking endpoints must work WITHOUT an Authorization header.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from apps.calendar_app.models import Booking, BookingStatus, ProviderSettings

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def provider_settings(db, admin_user):
    return ProviderSettings.get_for_provider(admin_user)
    return ProviderSettings.objects.get_or_create(user=admin_user)[0]


@pytest.fixture
def mock_google_service():
    """Mock Google Calendar API service for both views and Celery tasks."""
    with (
        patch("apps.calendar_app.services.booking_service._check_freebusy"),
        patch("apps.calendar_app.selectors.availability._build_service") as mock_build1,
        patch("apps.calendar_app.services.booking_service._build_service") as mock_build2,
        patch("apps.calendar_app.selectors.availability._get_admin_credential"),
        patch("apps.calendar_app.services.booking_service._get_admin_credential"),
        patch("apps.calendar_app.views._get_admin_credential"),
        patch("apps.calendar_app.views._build_service") as mock_build_views,
        patch("apps.calendar_app.tasks._get_service") as mock_task_svc,
    ):
        mock_service = MagicMock()
        mock_build1.return_value = mock_service
        mock_build2.return_value = mock_service
        mock_build_views.return_value = mock_service
        mock_task_svc.return_value = mock_service
        # Default: slot is free
        mock_service.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": []}}
        }
        yield mock_service


@pytest.fixture
def booked_booking(admin_user):
    return Booking.objects.create(
        email="existing@example.com",
        provider=admin_user,
        google_event_id="existing_evt_001",
        start_time=datetime.datetime(2026, 8, 4, 10, 0, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2026, 8, 4, 10, 30, tzinfo=datetime.UTC),
        reason="Existing booking",
        status=BookingStatus.CONFIRMED,
    )


# ─── Availability ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAvailabilityView:
    def test_availability_anonymous_no_auth_required(
        self, api_client, admin_user, mock_google_service
    ):
        """GET availability works with no Authorization header."""
        url = f"/api/v1/calendar/availability/?date=2026-07-27&provider_id={admin_user.id}"
        response = api_client.get(url)
        assert response.status_code == 200
        assert "available_slots" in response.data["data"]
        assert "timezone" in response.data["data"]

    def test_availability_returns_slots(self, api_client, admin_user, mock_google_service):
        url = f"/api/v1/calendar/availability/?date=2026-07-27&provider_id={admin_user.id}"
        response = api_client.get(url)
        assert response.status_code == 200
        slots = response.data["data"]["available_slots"]
        assert len(slots) > 0
        # Each slot should be exactly 30 minutes
        for slot in slots:
            start = datetime.datetime.fromisoformat(slot["start"])
            end = datetime.datetime.fromisoformat(slot["end"])
            assert (end - start).seconds == 1800

    def test_availability_weekend_returns_empty(self, api_client, admin_user):
        # Sunday
        url = f"/api/v1/calendar/availability/?date=2026-07-26&provider_id={admin_user.id}"
        response = api_client.get(url)
        assert response.status_code == 200
        assert response.data["data"]["available_slots"] == []
        assert "message" in response.data

    def test_availability_missing_date_param(self, api_client):
        response = api_client.get("/api/v1/calendar/availability/")
        assert response.status_code == 400

    def test_availability_invalid_date_format(self, api_client):
        response = api_client.get("/api/v1/calendar/availability/?date=not-a-date")
        assert response.status_code == 400


# ─── Book Appointment ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestBookAppointmentView:
    def test_book_anonymous_no_auth_required(self, api_client, mock_google_service, admin_user):
        """POST /api/v1/appointments/book/ works with no Authorization header."""
        mock_google_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "new_evt_001",
            "htmlLink": "https://calendar.google.com/...",
        }
        payload = {
            "email": "anon@example.com",
            "start_time": "2026-08-04T10:00:00+05:30",
            "reason": "Annual checkup",
            "provider_id": admin_user.id,
        }
        response = api_client.post("/api/v1/appointments/book/", payload, format="json")
        assert response.status_code == 201
        assert response.data["data"]["google_event_id"] == "new_evt_001"
        assert Booking.objects.filter(email="anon@example.com").exists()

    def test_book_end_time_is_always_30_minutes(self, api_client, mock_google_service, admin_user):
        """Server must always set end_time = start_time + 30 min."""
        mock_google_service.events.return_value.insert.return_value.execute.return_value = {
            "id": "new_evt_dur",
            "htmlLink": "",
        }
        payload = {
            "email": "dur@example.com",
            "start_time": "2026-08-04T14:00:00+05:30",
            "provider_id": admin_user.id,
        }
        response = api_client.post("/api/v1/appointments/book/", payload, format="json")
        assert response.status_code == 201
        booking = Booking.objects.get(email="dur@example.com")
        duration = (booking.end_time - booking.start_time).seconds // 60
        assert duration == 30

    def test_book_missing_email_returns_400(self, api_client, admin_user):
        payload = {
            "name": "No Email",
            "start_time": "2026-07-25T10:00:00Z",
            "provider_id": admin_user.id,
        }
        response = api_client.post("/api/v1/appointments/book/", payload, format="json")
        assert response.status_code == 400
        assert "email" in response.data["data"]

    def test_book_weekend_slot_rejected(self, api_client, mock_google_service, admin_user):
        # Saturday
        payload = {
            "email": "wknd@example.com",
            "start_time": "2026-08-01T10:00:00+05:30",
            "provider_id": admin_user.id,
        }
        response = api_client.post("/api/v1/appointments/book/", payload, format="json")
        assert response.status_code == 400

    @patch("apps.calendar_app.services.booking_service._check_freebusy")
    def test_book_conflicting_slot_returns_409(
        self, mock_freebusy, api_client, admin_user, mock_google_service
    ):
        mock_freebusy.return_value = False
        payload = {
            "email": "conflict@example.com",
            "start_time": "2026-08-04T10:00:00+05:30",
            "provider_id": admin_user.id,
        }
        response = api_client.post("/api/v1/appointments/book/", payload, format="json")
        assert response.status_code == 409

    def test_book_past_slot_rejected(self, api_client, admin_user):
        from django.utils import timezone

        past_time = timezone.now() - datetime.timedelta(days=1)
        payload = {
            "email": "past@example.com",
            "start_time": past_time.isoformat(),
            "provider_id": admin_user.id,
        }
        response = api_client.post("/api/v1/appointments/book/", payload, format="json")
        assert response.status_code == 400


# ─── List Bookings by Email ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestBookingsByEmailView:
    def test_list_bookings_by_email(self, api_client, booked_booking):
        response = api_client.get("/api/v1/appointments/by-email/?email=existing@example.com")
        assert response.status_code == 200
        assert len(response.data["data"]) == 1
        assert response.data["data"][0]["google_event_id"] == "existing_evt_001"

    def test_list_bookings_multiple_for_same_email(self, api_client):
        for i in range(3):
            Booking.objects.create(
                email="multi@example.com",
                google_event_id=f"multi_evt_{i}",
                start_time=datetime.datetime(2026, 8, i + 4, 10, 0, tzinfo=datetime.UTC),
                end_time=datetime.datetime(2026, 8, i + 4, 10, 30, tzinfo=datetime.UTC),
            )
        response = api_client.get("/api/v1/appointments/by-email/?email=multi@example.com")
        assert response.status_code == 200
        assert len(response.data["data"]) == 3

    def test_list_bookings_cancelled_excluded(self, api_client):
        Booking.objects.create(
            email="cancelled@example.com",
            google_event_id="cancelled_evt",
            start_time=datetime.datetime(2026, 8, 4, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 4, 10, 30, tzinfo=datetime.UTC),
            status=BookingStatus.CANCELLED,
        )
        response = api_client.get("/api/v1/appointments/by-email/?email=cancelled@example.com")
        assert response.status_code == 200
        assert len(response.data["data"]) == 0

    def test_list_bookings_missing_email_returns_400(self, api_client):
        response = api_client.get("/api/v1/appointments/by-email/")
        assert response.status_code == 400

    def test_list_bookings_unknown_email_returns_empty(self, api_client):
        response = api_client.get("/api/v1/appointments/by-email/?email=nobody@example.com")
        assert response.status_code == 200
        assert response.data["data"] == []


# ─── Reschedule ───────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRescheduleAppointmentView:
    def test_reschedule_success(self, api_client, booked_booking, mock_google_service):
        mock_google_service.events.return_value.patch.return_value.execute.return_value = {
            "id": "existing_evt_001",
            "htmlLink": "",
        }
        payload = {
            "email": "existing@example.com",
            "new_start_time": "2026-08-05T11:00:00+05:30",
        }
        response = api_client.patch(
            f"/api/v1/appointments/{booked_booking.google_event_id}/reschedule/",
            payload,
            format="json",
        )
        assert response.status_code == 200
        booked_booking.refresh_from_db()
        assert booked_booking.status == BookingStatus.RESCHEDULED

    def test_reschedule_wrong_email_returns_404(
        self, api_client, booked_booking, mock_google_service
    ):
        payload = {
            "email": "wrong@example.com",
            "new_start_time": "2026-08-05T11:00:00+05:30",
        }
        response = api_client.patch(
            f"/api/v1/appointments/{booked_booking.google_event_id}/reschedule/",
            payload,
            format="json",
        )
        assert response.status_code == 404

    @patch("apps.calendar_app.services.booking_service._check_freebusy")
    def test_reschedule_conflict_returns_409(
        self, mock_freebusy, api_client, booked_booking, mock_google_service
    ):
        mock_freebusy.return_value = False
        payload = {
            "email": "existing@example.com",
            "new_start_time": "2026-08-05T11:00:00+05:30",
        }
        response = api_client.patch(
            f"/api/v1/appointments/{booked_booking.google_event_id}/reschedule/",
            payload,
            format="json",
        )
        assert response.status_code == 409


# ─── Cancel ───────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCancelAppointmentView:
    def test_cancel_success(self, api_client, booked_booking, mock_google_service):
        mock_google_service.events.return_value.delete.return_value.execute.return_value = None
        payload = {"email": "existing@example.com"}
        response = api_client.delete(
            f"/api/v1/appointments/{booked_booking.google_event_id}/cancel/",
            payload,
            format="json",
        )
        assert response.status_code == 204
        booked_booking.refresh_from_db()
        assert booked_booking.status == BookingStatus.CANCELLED

    def test_cancel_wrong_email_returns_404(self, api_client, booked_booking):
        payload = {"email": "wrong@example.com"}
        response = api_client.delete(
            f"/api/v1/appointments/{booked_booking.google_event_id}/cancel/",
            payload,
            format="json",
        )
        assert response.status_code == 404

    def test_cancel_missing_email_returns_400(self, api_client, booked_booking):
        response = api_client.delete(
            f"/api/v1/appointments/{booked_booking.google_event_id}/cancel/",
            {},
            format="json",
        )
        assert response.status_code == 400


# ─── Admin routes remain protected ───────────────────────────────────────────


@pytest.mark.django_db
class TestAdminRoutesProtected:
    def test_provider_settings_requires_admin(self, api_client):
        response = api_client.get("/api/v1/admin/provider-settings/")
        assert response.status_code in [401, 403]
