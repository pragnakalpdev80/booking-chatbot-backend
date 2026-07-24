import logging

from apps.chatbot.agent import run_agentic_loop
from apps.chatbot.models import ConversationSession
from common.api.exceptions import ApplicationError
from common.services.base import BaseService

logger = logging.getLogger(__name__)


class AgenticService(BaseService):
    @classmethod
    def send_message(cls, session: ConversationSession, user_message: str) -> str:
        try:
            ai_response = run_agentic_loop(session, user_message)
            return ai_response
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agentic loop error for session %s: %s", session.session_key, exc)
            raise ApplicationError(
                "An error occurred processing your request. Please try again.",
                status_code=500,
            ) from exc
