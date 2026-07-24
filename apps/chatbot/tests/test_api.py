# apps/chatbot/tests/test_api.py
"""
API tests for anonymous chatbot session endpoints.
All endpoints must work WITHOUT an Authorization header.
"""

import uuid
from unittest.mock import patch

import pytest

from apps.chatbot.models import ConversationSession, Message, MessageRole


@pytest.mark.django_db
class TestStartSessionView:
    def test_start_session_anonymous_no_auth(self, api_client, admin_user):
        """POST /api/v1/chat/sessions/ must work with no auth token."""
        response = api_client.post("/api/v1/chat/sessions/", {"provider_id": admin_user.id})
        assert response.status_code == 201
        assert "session_key" in response.data["data"]
        assert ConversationSession.objects.count() == 1

    def test_start_session_returns_uuid(self, api_client, admin_user):
        response = api_client.post("/api/v1/chat/sessions/", {"provider_id": admin_user.id})
        assert response.status_code == 201
        # Should be a valid UUID
        session_key = response.data["data"]["session_key"]
        assert uuid.UUID(str(session_key))

    def test_start_session_user_email_initially_empty(self, api_client, admin_user):
        response = api_client.post("/api/v1/chat/sessions/", {"provider_id": admin_user.id})
        assert response.status_code == 201
        assert response.data["data"]["user_email"] in [None, ""]


@pytest.mark.django_db
class TestSendMessageView:
    @pytest.fixture
    def session(self, admin_user):
        return ConversationSession.objects.create(provider=admin_user)

    def test_send_message_no_auth_required(self, api_client, session):
        """POST /api/v1/chat/message/ must work with no auth token."""
        with patch(
            "apps.chatbot.services.agentic_service.run_agentic_loop",
            return_value="Hello! How can I help?",
        ):
            payload = {
                "session_key": str(session.session_key),
                "message": "Hi",
            }
            response = api_client.post("/api/v1/chat/message/", payload, format="json")
        assert response.status_code == 200
        assert response.data["data"]["response"] == "Hello! How can I help?"

    def test_send_message_unknown_session_returns_404(self, api_client):
        payload = {
            "session_key": str(uuid.uuid4()),
            "message": "Hi",
        }
        response = api_client.post("/api/v1/chat/message/", payload, format="json")
        assert response.status_code == 404

    def test_send_message_missing_session_key_returns_400(self, api_client):
        payload = {"message": "Hi"}
        response = api_client.post("/api/v1/chat/message/", payload, format="json")
        assert response.status_code == 400

    def test_send_message_empty_message_returns_400(self, api_client, session):
        payload = {"session_key": str(session.session_key), "message": ""}
        response = api_client.post("/api/v1/chat/message/", payload, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
class TestSessionHistoryView:
    @pytest.fixture
    def session_with_messages(self, admin_user):
        session = ConversationSession.objects.create(
            user_email="hist@example.com", provider=admin_user
        )
        Message.objects.create(session=session, role=MessageRole.USER, content="Hello")
        Message.objects.create(session=session, role=MessageRole.ASSISTANT, content="Hi there!")
        # Tool message — should be hidden in history
        Message.objects.create(
            session=session,
            role=MessageRole.TOOL,
            content='{"status": "ok"}',
            tool_call_id="call_1",
        )
        return session

    def test_history_no_auth_required(self, api_client, session_with_messages):
        response = api_client.get(
            f"/api/v1/chat/sessions/{session_with_messages.session_key}/messages/"
        )
        assert response.status_code == 200

    def test_history_excludes_tool_messages(self, api_client, session_with_messages):
        response = api_client.get(
            f"/api/v1/chat/sessions/{session_with_messages.session_key}/messages/"
        )
        assert response.status_code == 200
        roles = [m["role"] for m in response.data["data"]["messages"]]
        assert "tool" not in roles
        assert len(response.data["data"]["messages"]) == 2

    def test_history_shows_user_email(self, api_client, session_with_messages):
        response = api_client.get(
            f"/api/v1/chat/sessions/{session_with_messages.session_key}/messages/"
        )
        assert response.data["data"]["user_email"] == "hist@example.com"

    def test_history_unknown_session_returns_404(self, api_client):
        response = api_client.get(f"/api/v1/chat/sessions/{uuid.uuid4()}/messages/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestDeleteSessionView:
    def test_delete_session_no_auth_required(self, api_client, admin_user):
        session = ConversationSession.objects.create(provider=admin_user)
        response = api_client.delete(f"/api/v1/chat/sessions/{session.session_key}/")
        assert response.status_code == 204
        assert ConversationSession.objects.filter(pk=session.pk).count() == 0

    def test_delete_unknown_session_returns_404(self, api_client):
        response = api_client.delete(f"/api/v1/chat/sessions/{uuid.uuid4()}/")
        assert response.status_code == 404
