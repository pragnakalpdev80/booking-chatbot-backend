import logging
from typing import Any

from django.contrib.auth import get_user_model

from apps.chatbot.models import ConversationSession
from common.api.exceptions import ApplicationError
from common.services.base import BaseService

logger = logging.getLogger(__name__)

User = get_user_model()


class ChatSessionService(BaseService):
    @classmethod
    def start_session(cls, provider_id: Any) -> ConversationSession:
        try:
            provider = User.objects.get(pk=provider_id)
        except User.DoesNotExist as exc:
            raise ApplicationError("Provider not found", status_code=404) from exc

        session = ConversationSession.objects.create(provider=provider)
        logger.info(
            "New anonymous chat session %s created for provider %s",
            session.session_key,
            provider.username,
        )
        return session

    @classmethod
    def get_session(cls, session_id: str) -> ConversationSession:
        try:
            return ConversationSession.objects.get(session_key=session_id)
        except ConversationSession.DoesNotExist as exc:
            raise ApplicationError("Session not found.", status_code=404) from exc

    @classmethod
    def delete_session(cls, session_key: str) -> None:
        try:
            session = ConversationSession.objects.get(session_key=session_key)
            session.delete()
            logger.info("Session %s deleted", session_key)
        except ConversationSession.DoesNotExist as exc:
            raise ApplicationError("Session not found.", status_code=404) from exc
