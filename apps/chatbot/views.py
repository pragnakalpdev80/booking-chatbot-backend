# chatbot/views.py
"""
Anonymous chatbot API endpoints.

All endpoints use AllowAny — no JWT required.
Sessions are identified by a client-managed UUID (session_key).

POST   /api/chat/sessions/                       — start a new anonymous session
POST   /api/chat/message/                        — send a message; receive AI response
GET    /api/chat/sessions/<session_key>/messages/ — retrieve session history
DELETE /api/chat/sessions/<session_key>/          — delete/end a session
"""

import logging

from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.chatbot.services.agentic_service import AgenticService
from apps.chatbot.services.session_service import ChatSessionService
from common.api.exceptions import ApplicationError
from common.api.response import ApiResponse

from .serializers import (
    ConversationSessionSerializer,
    MessageSerializer,
    SendMessageSerializer,
)

logger = logging.getLogger(__name__)


class StartSessionSerializer(serializers.Serializer):
    provider_id = serializers.IntegerField()


class StartSessionView(APIView):
    """POST /api/chat/sessions/ — create a new anonymous conversation session."""

    permission_classes = [AllowAny]

    def post(self, request):
        logger.debug("StartSessionView POST — anonymous session creation")
        serializer = StartSessionSerializer(data=request.data)
        if not serializer.is_valid():
            return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        provider_id = serializer.validated_data["provider_id"]

        try:
            session = ChatSessionService.start_session(provider_id)
            return ApiResponse(
                ConversationSessionSerializer(session).data,
                status=status.HTTP_201_CREATED,
            )
        except ApplicationError as e:
            return ApiResponse({"error": str(e)}, status=e.status_code)


class SendMessageView(APIView):
    """
    POST /api/chat/message/

    Body: { "session_key": "<uuid>", "message": "<user text>" }
    Returns: { "response": "<AI reply>" }
    """

    permission_classes = [AllowAny]

    def post(self, request):
        logger.debug("SendMessageView POST received")
        serializer = SendMessageSerializer(data=request.data)
        if not serializer.is_valid():
            return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_key = serializer.validated_data["session_key"]
        user_message = serializer.validated_data["message"]

        try:
            session = ChatSessionService.get_session(session_key)
            ai_response = AgenticService.send_message(session, user_message)
            return ApiResponse({"response": ai_response})
        except ApplicationError as e:
            return ApiResponse({"error": str(e)}, status=e.status_code)


class SessionHistoryView(APIView):
    """GET /api/chat/sessions/<session_key>/messages/ — retrieve session history."""

    permission_classes = [AllowAny]

    def get(self, request, session_key):
        logger.debug("SessionHistoryView GET for session %s", session_key)
        try:
            session = ChatSessionService.get_session(session_key)
            # Exclude internal tool messages — only show user and assistant turns
            messages = session.messages.exclude(role="tool").order_by("timestamp")
            return ApiResponse(
                {
                    "session_key": str(session.session_key),
                    "user_email": session.user_email or None,
                    "messages": MessageSerializer(messages, many=True).data,
                }
            )
        except ApplicationError as e:
            return ApiResponse({"error": str(e)}, status=e.status_code)


class DeleteSessionView(APIView):
    """DELETE /api/chat/sessions/<session_key>/ — end and delete a session."""

    permission_classes = [AllowAny]

    def delete(self, request, session_key):
        logger.debug("DeleteSessionView DELETE for session %s", session_key)
        try:
            ChatSessionService.delete_session(session_key)
            return ApiResponse(status=status.HTTP_204_NO_CONTENT)
        except ApplicationError as e:
            return ApiResponse({"error": str(e)}, status=e.status_code)
