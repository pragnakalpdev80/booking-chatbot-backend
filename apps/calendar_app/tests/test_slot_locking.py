import json
from datetime import timedelta

import pytest
from django.utils.timezone import now

from apps.calendar_app.models import SlotLock
from apps.chatbot.models import ConversationSession
from apps.chatbot.tools import _lock_slot, _release_slot


@pytest.fixture
def session(admin_user):
    return ConversationSession.objects.create(provider=admin_user)


@pytest.fixture
def other_session(admin_user):
    return ConversationSession.objects.create(provider=admin_user)


@pytest.mark.django_db
def test_lock_slot_success(mocker, session):
    mocker.patch("apps.chatbot.tools.get_gcal_service")
    mocker.patch("apps.chatbot.tools.check_freebusy", return_value=True)

    start_time = (now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    res_str = _lock_slot(session, start_time.isoformat())
    res = json.loads(res_str)

    assert res.get("status") == "locked"
    assert "expires_at" in res

    assert SlotLock.objects.filter(session_key=session.session_key).count() == 1


@pytest.mark.django_db
def test_lock_slot_conflict(mocker, session, other_session):
    mocker.patch("apps.chatbot.tools.get_gcal_service")
    mocker.patch("apps.chatbot.tools.check_freebusy", return_value=True)

    start_time = (now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    # First user locks
    _lock_slot(session, start_time.isoformat())

    # Second user tries to lock same slot
    res_str2 = _lock_slot(other_session, start_time.isoformat())
    res2 = json.loads(res_str2)

    assert "error" in res2
    assert "currently being booked" in res2["error"]


@pytest.mark.django_db
def test_release_slot(mocker, session):
    mocker.patch("apps.chatbot.tools.get_gcal_service")
    mocker.patch("apps.chatbot.tools.check_freebusy", return_value=True)

    start_time = (now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    _lock_slot(session, start_time.isoformat())
    assert SlotLock.objects.filter(session_key=session.session_key).count() == 1

    res_str = _release_slot(session, start_time.isoformat())
    res = json.loads(res_str)

    assert res.get("status") == "released"
    assert SlotLock.objects.filter(session_key=session.session_key).count() == 0


# ── Cross-provider isolation tests (Bug 1 regression guards) ──────────────────


@pytest.mark.django_db
def test_lock_does_not_block_other_provider(mocker, admin_user, user):
    """A SlotLock held by provider A must NOT block provider B from locking the same slot.

    Regression test for: SlotLock queries were missing provider= scope, causing
    a lock under one provider to appear as a conflict for all other providers.
    """
    mocker.patch("apps.chatbot.tools.get_gcal_service")
    mocker.patch("apps.chatbot.tools.check_freebusy", return_value=True)

    start_time = (now() + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)

    # Provider A (admin_user) locks the slot
    session_a = ConversationSession.objects.create(provider=admin_user)
    res_a = json.loads(_lock_slot(session_a, start_time.isoformat()))
    assert res_a.get("status") == "locked", f"Provider A lock failed: {res_a}"

    # Provider B (user) must be able to lock the same slot independently
    session_b = ConversationSession.objects.create(provider=user)
    res_b = json.loads(_lock_slot(session_b, start_time.isoformat()))
    assert res_b.get("status") == "locked", (
        f"Provider B was incorrectly blocked by provider A's lock: {res_b}"
    )


@pytest.mark.django_db
def test_confirmed_booking_only_blocks_same_provider(mocker, admin_user, user):
    """A confirmed Booking for provider A must NOT block provider B from locking the same slot.

    Regression test for: Booking confirmed-booking guard was missing provider= scope.
    """
    from apps.calendar_app.models import Booking, BookingStatus

    mocker.patch("apps.chatbot.tools.get_gcal_service")
    mocker.patch("apps.chatbot.tools.check_freebusy", return_value=True)

    start_time = (now() + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)

    # Create a confirmed booking for provider A
    Booking.objects.create(
        email="patient@example.com",
        provider=admin_user,
        google_event_id="test_event_001",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=30),
        reason="Test",
        status=BookingStatus.CONFIRMED,
    )

    # Provider B must be able to lock the same time slot without error
    session_b = ConversationSession.objects.create(provider=user)
    res_b = json.loads(_lock_slot(session_b, start_time.isoformat()))
    assert res_b.get("status") == "locked", (
        f"Provider B was incorrectly blocked by provider A's confirmed booking: {res_b}"
    )
