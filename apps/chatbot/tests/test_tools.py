# apps/chatbot/tests/test_tools.py
"""
Unit tests for chatbot tool executor functions.
All Google API calls are mocked.
"""

import datetime
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils.timezone import now

from apps.calendar_app.models import Booking, BookingStatus, ProviderSettings, SlotLock
from apps.chatbot.models import ConversationSession
from apps.chatbot.tools import execute_tool


@pytest.fixture(autouse=True)
def provider_settings(db):
    return ProviderSettings.get_instance()


@pytest.fixture
def session(db):
    return ConversationSession.objects.create()


@pytest.fixture
def session_with_email(db):
    return ConversationSession.objects.create(user_email="user@example.com")


@pytest.fixture
def booking(db, session_with_email):
    return Booking.objects.create(
        email="user@example.com",
        google_event_id="tool_evt_001",
        start_time=datetime.datetime(2026, 8, 4, 10, 0, tzinfo=datetime.UTC),
        end_time=datetime.datetime(2026, 8, 4, 10, 30, tzinfo=datetime.UTC),
    )


@pytest.fixture
def mock_service():
    with patch("apps.chatbot.tools._get_service") as mock_get:
        svc = MagicMock()
        mock_get.return_value = svc
        svc.freebusy().query().execute.return_value = {"calendars": {"primary": {"busy": []}}}
        yield svc


# ─── save_session_email ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestSaveSessionEmailTool:
    def test_saves_email_to_session(self, session):
        result = json.loads(
            execute_tool("save_session_email", {"email": "new@example.com"}, session)
        )
        session.refresh_from_db()
        assert result["status"] == "email_saved"
        assert session.user_email == "new@example.com"

    def test_email_is_lowercased(self, session):
        execute_tool("save_session_email", {"email": "UPPER@EXAMPLE.COM"}, session)
        session.refresh_from_db()
        assert session.user_email == "upper@example.com"

    def test_overwrites_previous_email(self, session_with_email):
        execute_tool("save_session_email", {"email": "new@example.com"}, session_with_email)
        session_with_email.refresh_from_db()
        assert session_with_email.user_email == "new@example.com"


# ─── get_available_slots ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestGetAvailableSlotsTool:
    def test_returns_slots_for_weekday(self, session, mock_service):
        result = json.loads(execute_tool("get_available_slots", {"date": "2026-08-03"}, session))
        assert "available_slots" in result
        assert result["slot_duration_minutes"] == 30
        assert len(result["available_slots"]) > 0

    def test_each_slot_is_30_minutes(self, session, mock_service):
        result = json.loads(execute_tool("get_available_slots", {"date": "2026-08-03"}, session))
        for slot in result["available_slots"]:
            start = datetime.datetime.fromisoformat(slot["start"])
            end = datetime.datetime.fromisoformat(slot["end"])
            assert (end - start).seconds == 1800

    def test_returns_empty_for_weekend(self, session, mock_service):
        result = json.loads(execute_tool("get_available_slots", {"date": "2026-08-01"}, session))
        assert result["available_slots"] == []

    def test_invalid_date_returns_error(self, session):
        result = json.loads(execute_tool("get_available_slots", {"date": "bad-date"}, session))
        assert "error" in result

    def test_busy_slot_excluded(self, session, mock_service):
        mock_service.freebusy().query().execute.return_value = {
            "calendars": {
                "primary": {
                    "busy": [{"start": "2026-08-03T03:30:00Z", "end": "2026-08-03T04:00:00Z"}]
                }
            }
        }
        result = json.loads(execute_tool("get_available_slots", {"date": "2026-08-03"}, session))
        starts = [s["start"] for s in result["available_slots"]]
        assert not any("09:00" in s for s in starts)


# ─── book_appointment ─────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestBookAppointmentTool:
    def test_book_creates_booking_record(self, session_with_email, mock_service):
        mock_service.events().insert().execute.return_value = {
            "id": "new_tool_evt",
            "htmlLink": "",
        }
        SlotLock.objects.create(
            session_key=session_with_email.session_key,
            slot_start="2026-08-04T10:00:00+05:30",
            slot_end="2026-08-04T10:30:00+05:30",
            expires_at=now() + timedelta(minutes=15),
        )
        result = json.loads(
            execute_tool(
                "book_appointment",
                {"start_time": "2026-08-04T10:00:00+05:30", "reason": "Checkup"},
                session_with_email,
            )
        )
        assert result["status"] == "confirmed"
        assert Booking.objects.filter(email="user@example.com").exists()

    def test_book_end_time_always_30_minutes(self, session_with_email, mock_service):
        mock_service.events().insert().execute.return_value = {"id": "dur_evt", "htmlLink": ""}
        SlotLock.objects.create(
            session_key=session_with_email.session_key,
            slot_start="2026-08-04T09:00:00+05:30",
            slot_end="2026-08-04T09:30:00+05:30",
            expires_at=now() + timedelta(minutes=15),
        )
        execute_tool(
            "book_appointment", {"start_time": "2026-08-04T09:00:00+05:30"}, session_with_email
        )
        booking = Booking.objects.get(email="user@example.com")
        duration = (booking.end_time - booking.start_time).seconds // 60
        assert duration == 30

    def test_book_without_email_returns_error(self, session):
        result = json.loads(
            execute_tool(
                "book_appointment",
                {"start_time": "2026-08-04T10:00:00+05:30"},
                session,
            )
        )
        assert "error" in result
        assert "email" in result["error"].lower()

    def test_book_busy_slot_returns_error(self, session_with_email, mock_service):
        mock_service.freebusy().query().execute.return_value = {
            "calendars": {
                "primary": {
                    "busy": [{"start": "2026-08-04T04:30:00Z", "end": "2026-08-04T05:00:00Z"}]
                }
            }
        }
        result = json.loads(
            execute_tool(
                "book_appointment",
                {"start_time": "2026-08-04T10:00:00+05:30"},
                session_with_email,
            )
        )
        assert "error" in result


# ─── reschedule_appointment ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestRescheduleAppointmentTool:
    def test_reschedule_success(self, session_with_email, booking, mock_service):
        mock_service.events().patch().execute.return_value = {"id": "tool_evt_001", "htmlLink": ""}
        result = json.loads(
            execute_tool(
                "reschedule_appointment",
                {"event_id": "tool_evt_001", "new_start_time": "2026-08-05T11:00:00+05:30"},
                session_with_email,
            )
        )
        assert result["status"] == "rescheduled"
        booking.refresh_from_db()
        assert booking.status == BookingStatus.RESCHEDULED

    def test_reschedule_new_duration_is_30_minutes(self, session_with_email, booking, mock_service):
        mock_service.events().patch().execute.return_value = {"id": "tool_evt_001", "htmlLink": ""}
        execute_tool(
            "reschedule_appointment",
            {"event_id": "tool_evt_001", "new_start_time": "2026-08-05T11:00:00+05:30"},
            session_with_email,
        )
        booking.refresh_from_db()
        duration = (booking.end_time - booking.start_time).seconds // 60
        assert duration == 30

    def test_reschedule_without_email_returns_error(self, session, booking):
        result = json.loads(
            execute_tool(
                "reschedule_appointment",
                {"event_id": "tool_evt_001", "new_start_time": "2026-08-05T11:00:00+05:30"},
                session,
            )
        )
        assert "error" in result

    def test_reschedule_wrong_email_returns_error(self, session_with_email, mock_service):
        Booking.objects.create(
            email="other@example.com",
            google_event_id="other_evt",
            start_time=datetime.datetime(2026, 8, 4, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 4, 10, 30, tzinfo=datetime.UTC),
        )
        result = json.loads(
            execute_tool(
                "reschedule_appointment",
                {"event_id": "other_evt", "new_start_time": "2026-08-05T11:00:00+05:30"},
                session_with_email,  # email = user@example.com, not other@example.com
            )
        )
        assert "error" in result


# ─── cancel_appointment ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCancelAppointmentTool:
    def test_cancel_success(self, session_with_email, booking, mock_service):
        mock_service.events().delete().execute.return_value = None
        result = json.loads(
            execute_tool(
                "cancel_appointment",
                {"event_id": "tool_evt_001"},
                session_with_email,
            )
        )
        assert result["status"] == "cancelled"
        booking.refresh_from_db()
        assert booking.status == BookingStatus.CANCELLED

    def test_cancel_without_email_returns_error(self, session, booking):
        result = json.loads(
            execute_tool(
                "cancel_appointment",
                {"event_id": "tool_evt_001"},
                session,
            )
        )
        assert "error" in result

    def test_cancel_wrong_email_returns_error(self, session_with_email):
        Booking.objects.create(
            email="wrong@example.com",
            google_event_id="wrong_evt",
            start_time=datetime.datetime(2026, 8, 4, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 4, 10, 30, tzinfo=datetime.UTC),
        )
        result = json.loads(
            execute_tool(
                "cancel_appointment",
                {"event_id": "wrong_evt"},
                session_with_email,  # email = user@example.com
            )
        )
        assert "error" in result


# ─── list_my_appointments ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestListMyAppointmentsTool:
    def test_list_returns_bookings_for_email(self, session_with_email, booking):
        result = json.loads(execute_tool("list_my_appointments", {}, session_with_email))
        assert result["count"] == 1
        assert result["appointments"][0]["google_event_id"] == "tool_evt_001"

    def test_list_multiple_bookings_same_email(self, session_with_email):
        for i in range(3):
            Booking.objects.create(
                email="user@example.com",
                google_event_id=f"multi_tool_evt_{i}",
                start_time=datetime.datetime(2026, 8, i + 4, 10, 0, tzinfo=datetime.UTC),
                end_time=datetime.datetime(2026, 8, i + 4, 10, 30, tzinfo=datetime.UTC),
            )
        result = json.loads(execute_tool("list_my_appointments", {}, session_with_email))
        assert result["count"] == 3

    def test_list_excludes_cancelled(self, session_with_email):
        Booking.objects.create(
            email="user@example.com",
            google_event_id="cancelled_tool_evt",
            start_time=datetime.datetime(2026, 8, 4, 10, 0, tzinfo=datetime.UTC),
            end_time=datetime.datetime(2026, 8, 4, 10, 30, tzinfo=datetime.UTC),
            status=BookingStatus.CANCELLED,
        )
        result = json.loads(execute_tool("list_my_appointments", {}, session_with_email))
        assert result["count"] == 0

    def test_list_without_email_returns_error(self, session):
        result = json.loads(execute_tool("list_my_appointments", {}, session))
        assert "error" in result

    def test_unknown_tool_returns_error(self, session):
        result = json.loads(execute_tool("nonexistent_tool", {}, session))
        assert "error" in result
