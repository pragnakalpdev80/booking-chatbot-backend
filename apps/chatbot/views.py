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

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .agent import run_agentic_loop
from .models import ConversationSession
from .serializers import (
    ConversationSessionSerializer,
    MessageSerializer,
    SendMessageSerializer,
)

logger = logging.getLogger(__name__)


class StartSessionView(APIView):
    """POST /api/chat/sessions/ — create a new anonymous conversation session."""

    permission_classes = [AllowAny]

    def post(self, request):
        logger.debug("StartSessionView POST — anonymous session creation")
        session = ConversationSession.objects.create()
        logger.info("New anonymous chat session %s created", session.session_key)
        return Response(
            ConversationSessionSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )


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
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        session_key = serializer.validated_data["session_key"]
        user_message = serializer.validated_data["message"]

        try:
            session = ConversationSession.objects.get(session_key=session_key)
        except ConversationSession.DoesNotExist:
            return Response(
                {"error": "Session not found. Please start a new session."},
                status=status.HTTP_404_NOT_FOUND,
            )

        logger.info("Received message for session %s", session_key)

        try:
            ai_response = run_agentic_loop(session, user_message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agentic loop error for session %s: %s", session_key, exc)
            return Response(
                {"error": "An error occurred processing your request. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response({"response": ai_response})


class SessionHistoryView(APIView):
    """GET /api/chat/sessions/<session_key>/messages/ — retrieve session history."""

    permission_classes = [AllowAny]

    def get(self, request, session_key):
        logger.debug("SessionHistoryView GET for session %s", session_key)
        try:
            session = ConversationSession.objects.get(session_key=session_key)
        except ConversationSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        # Exclude internal tool messages — only show user and assistant turns
        messages = session.messages.exclude(role="tool").order_by("timestamp")
        return Response(
            {
                "session_key": str(session.session_key),
                "user_email": session.user_email or None,
                "messages": MessageSerializer(messages, many=True).data,
            }
        )


class DeleteSessionView(APIView):
    """DELETE /api/chat/sessions/<session_key>/ — end and delete a session."""

    permission_classes = [AllowAny]

    def delete(self, request, session_key):
        logger.debug("DeleteSessionView DELETE for session %s", session_key)
        try:
            session = ConversationSession.objects.get(session_key=session_key)
        except ConversationSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        session.delete()
        logger.info("Session %s deleted", session_key)
        return Response(status=status.HTTP_204_NO_CONTENT)
