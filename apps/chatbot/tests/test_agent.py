import json
from unittest.mock import MagicMock, patch

import pytest

from apps.calendar_app.models import ProviderSettings
from apps.chatbot.agent import run_agentic_loop
from apps.chatbot.models import ConversationSession, MessageRole


@pytest.fixture(autouse=True)
def provider_settings(db):
    return ProviderSettings.get_instance()


@pytest.fixture
def session(db):
    return ConversationSession.objects.create()


@pytest.mark.django_db
class TestAgenticLoop:
    @patch("apps.chatbot.agent.Groq")
    @patch("apps.chatbot.agent.execute_tool")
    def test_run_agentic_loop_text_only(self, mock_execute_tool, MockGroq, session):
        """Test a simple text-only interaction with no tool calls."""
        # Setup mock Groq response
        mock_client = MagicMock()
        MockGroq.return_value = mock_client

        mock_choice = MagicMock()
        mock_choice.finish_reason = "stop"
        mock_choice.message.tool_calls = None
        mock_choice.message.content = "Hello! How can I help you today?"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        # Run the loop
        response_text = run_agentic_loop(session, "Hi there")

        # Verify response
        assert response_text == "Hello! How can I help you today?"

        # Verify messages persisted
        messages = list(session.messages.all())
        assert len(messages) == 2
        assert messages[0].role == MessageRole.USER
        assert messages[0].content == "Hi there"
        assert messages[1].role == MessageRole.ASSISTANT
        assert messages[1].content == "Hello! How can I help you today?"

        # Verify tool was not called
        mock_execute_tool.assert_not_called()

    @patch("apps.chatbot.agent.Groq")
    @patch("apps.chatbot.agent.execute_tool")
    def test_run_agentic_loop_with_tool_call(self, mock_execute_tool, MockGroq, session):
        """Test an interaction where the agent calls a tool and then responds."""
        mock_client = MagicMock()
        MockGroq.return_value = mock_client

        # First LLM response: call a tool
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_123"
        mock_tool_call.function.name = "save_session_email"
        mock_tool_call.function.arguments = '{"email": "test@example.com"}'

        mock_choice_1 = MagicMock()
        mock_choice_1.finish_reason = "tool_calls"
        mock_choice_1.message.tool_calls = [mock_tool_call]
        mock_choice_1.message.content = None

        mock_response_1 = MagicMock()
        mock_response_1.choices = [mock_choice_1]

        # Tool executor mock response
        mock_execute_tool.return_value = json.dumps(
            {"status": "email_saved", "email": "test@example.com"}
        )

        # Second LLM response: final text
        mock_choice_2 = MagicMock()
        mock_choice_2.finish_reason = "stop"
        mock_choice_2.message.tool_calls = None
        mock_choice_2.message.content = "I have saved your email."

        mock_response_2 = MagicMock()
        mock_response_2.choices = [mock_choice_2]

        # Set up side_effect to return the two responses in sequence
        mock_client.chat.completions.create.side_effect = [mock_response_1, mock_response_2]

        # Run the loop
        response_text = run_agentic_loop(session, "My email is test@example.com")

        # Verify response
        assert response_text == "I have saved your email."

        # Verify execute_tool was called correctly
        mock_execute_tool.assert_called_once_with(
            "save_session_email", {"email": "test@example.com"}, session
        )

        # Verify messages persisted
        messages = list(session.messages.order_by("timestamp"))
        assert len(messages) == 3
        assert messages[0].role == MessageRole.USER
        assert messages[1].role == MessageRole.TOOL
        assert messages[1].tool_call_id == "call_123"
        assert messages[1].content == '{"status": "email_saved", "email": "test@example.com"}'
        assert messages[2].role == MessageRole.ASSISTANT
        assert messages[2].content == "I have saved your email."

    @patch("apps.chatbot.agent.Groq")
    @patch("apps.chatbot.agent.execute_tool")
    def test_run_agentic_loop_max_iterations(self, mock_execute_tool, MockGroq, session):
        """Test that the loop breaks if MAX_TOOL_ITERATIONS is reached."""
        mock_client = MagicMock()
        MockGroq.return_value = mock_client

        # LLM response always calls a tool
        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_infinite"
        mock_tool_call.function.name = "get_available_slots"
        mock_tool_call.function.arguments = '{"date": "2026-08-01"}'

        mock_choice = MagicMock()
        mock_choice.finish_reason = "tool_calls"
        mock_choice.message.tool_calls = [mock_tool_call]
        mock_choice.message.content = None

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        # Always return the tool call response
        mock_client.chat.completions.create.return_value = mock_response

        # Mock tool executor
        mock_execute_tool.return_value = json.dumps({"status": "ok"})

        # Run the loop
        response_text = run_agentic_loop(session, "Find a slot")

        # It should exit gracefully with the fallback message
        assert (
            response_text == "I'm sorry, I wasn't able to process your request. Please try again."
        )

        # Should have iterated 5 times
        assert mock_execute_tool.call_count == 5
