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
    mocker.patch("apps.chatbot.tools._get_service")
    mocker.patch("apps.chatbot.tools._check_freebusy", return_value=True)

    start_time = (now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    res_str = _lock_slot(session, start_time.isoformat())
    res = json.loads(res_str)

    assert res.get("status") == "locked"
    assert "expires_at" in res

    assert SlotLock.objects.filter(session_key=session.session_key).count() == 1


@pytest.mark.django_db
def test_lock_slot_conflict(mocker, session, other_session):
    mocker.patch("apps.chatbot.tools._get_service")
    mocker.patch("apps.chatbot.tools._check_freebusy", return_value=True)

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
    mocker.patch("apps.chatbot.tools._get_service")
    mocker.patch("apps.chatbot.tools._check_freebusy", return_value=True)

    start_time = (now() + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    _lock_slot(session, start_time.isoformat())
    assert SlotLock.objects.filter(session_key=session.session_key).count() == 1

    res_str = _release_slot(session, start_time.isoformat())
    res = json.loads(res_str)

    assert res.get("status") == "released"
    assert SlotLock.objects.filter(session_key=session.session_key).count() == 0
