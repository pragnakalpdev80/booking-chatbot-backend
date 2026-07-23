# apps/chatbot/tests/test_models.py
"""
Unit tests for chatbot models.
Verifies anonymous ConversationSession creation and Message storage.
"""

import uuid

import pytest

from apps.chatbot.models import ConversationSession, Message, MessageRole


@pytest.mark.django_db
class TestConversationSessionModel:
    def test_session_created_without_user(self):
        """Session must be creatable with no user FK."""
        session = ConversationSession.objects.create()
        assert session.pk is not None
        assert session.session_key is not None
        assert session.user_email == ""
        assert session.intent == ""
        assert session.pending_slot is None

    def test_session_key_is_uuid(self):
        session = ConversationSession.objects.create()
        assert isinstance(session.session_key, uuid.UUID)

    def test_session_key_is_unique(self):
        s1 = ConversationSession.objects.create()
        s2 = ConversationSession.objects.create()
        assert s1.session_key != s2.session_key

    def test_user_email_can_be_set(self):
        session = ConversationSession.objects.create()
        session.user_email = "test@example.com"
        session.save(update_fields=["user_email", "updated_at"])
        session.refresh_from_db()
        assert session.user_email == "test@example.com"

    def test_pending_slot_stores_json(self):
        session = ConversationSession.objects.create()
        slot = {"start": "2026-08-04T10:00:00+05:30", "end": "2026-08-04T10:30:00+05:30"}
        session.pending_slot = slot
        session.save(update_fields=["pending_slot", "updated_at"])
        session.refresh_from_db()
        assert session.pending_slot == slot

    def test_session_str_includes_email(self):
        session = ConversationSession.objects.create()
        session.user_email = "str@example.com"
        session.save()
        assert "str@example.com" in str(session)

    def test_session_str_anonymous_when_no_email(self):
        session = ConversationSession.objects.create()
        assert "anonymous" in str(session)


@pytest.mark.django_db
class TestMessageModel:
    def test_message_created_for_session(self):
        session = ConversationSession.objects.create()
        msg = Message.objects.create(
            session=session,
            role=MessageRole.USER,
            content="Hello, I want to book.",
        )
        assert msg.pk is not None
        assert msg.role == "user"
        assert msg.content == "Hello, I want to book."

    def test_tool_message_stores_tool_call_id(self):
        session = ConversationSession.objects.create()
        msg = Message.objects.create(
            session=session,
            role=MessageRole.TOOL,
            content='{"status": "confirmed"}',
            tool_call_id="call_abc123",
        )
        assert msg.tool_call_id == "call_abc123"

    def test_message_ordering_by_timestamp(self):
        session = ConversationSession.objects.create()
        m1 = Message.objects.create(session=session, role=MessageRole.USER, content="First")
        m2 = Message.objects.create(session=session, role=MessageRole.ASSISTANT, content="Second")
        messages = list(session.messages.all())
        assert messages[0].pk == m1.pk
        assert messages[1].pk == m2.pk
