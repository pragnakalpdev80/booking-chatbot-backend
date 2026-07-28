import json
from unittest.mock import MagicMock, patch

import pytest

from apps.calendar_app.models import ProviderSettings
from apps.chatbot.agent import run_agentic_loop
from apps.chatbot.models import ConversationSession, MessageRole


@pytest.fixture(autouse=True)
def provider_settings(admin_user):
    return ProviderSettings.get_for_provider(admin_user)


@pytest.fixture
def session(admin_user):
    return ConversationSession.objects.create(provider=admin_user)


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
        assert response_text == (
            "I'm sorry, I wasn't able to fully process your request. "
            "Please try rephrasing or start a new conversation."
        )

        # Should have iterated MAX_TOOL_ITERATIONS (8) times
        assert mock_execute_tool.call_count == 8

    @patch("apps.chatbot.agent.Groq")
    @patch("apps.chatbot.agent.ProviderSettings.get_for_provider")
    def test_book_appointment_excluded_when_payment_required(self, mock_get_ps, MockGroq, session):
        """When payment_required is True, book_appointment must not be in available_tools."""
        # Setup mock PS
        mock_ps = MagicMock()
        mock_ps.payment_required = True
        mock_ps.timezone = "UTC"
        mock_ps.day_schedules = {"0": {"is_active": True, "start": "09:00", "end": "17:00"}}
        mock_ps.slot_duration = 30
        mock_get_ps.return_value = mock_ps

        mock_client = MagicMock()
        MockGroq.return_value = mock_client

        mock_choice = MagicMock()
        mock_choice.finish_reason = "stop"
        mock_choice.message.tool_calls = None
        mock_choice.message.content = "Ok"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        run_agentic_loop(session, "Hi")

        # Get the tools arg passed to Groq
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        available_tools = call_kwargs["tools"]
        tool_names = [t["function"]["name"] for t in available_tools]

        assert "initiate_payment" in tool_names
        assert "book_appointment" not in tool_names

    @patch("apps.chatbot.agent.Groq")
    @patch("apps.chatbot.agent.ProviderSettings.get_for_provider")
    def test_initiate_payment_excluded_when_payment_not_required(
        self,
        mock_get_ps,
        MockGroq,
        session,
    ):
        """When payment_required is False, initiate_payment must not be in available_tools."""
        # Setup mock PS
        mock_ps = MagicMock()
        mock_ps.payment_required = False
        mock_ps.timezone = "UTC"
        mock_ps.day_schedules = {"0": {"is_active": True, "start": "09:00", "end": "17:00"}}
        mock_ps.slot_duration = 30
        mock_get_ps.return_value = mock_ps

        mock_client = MagicMock()
        MockGroq.return_value = mock_client

        mock_choice = MagicMock()
        mock_choice.finish_reason = "stop"
        mock_choice.message.tool_calls = None
        mock_choice.message.content = "Ok"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        run_agentic_loop(session, "Hi")

        # Get the tools arg passed to Groq
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        available_tools = call_kwargs["tools"]
        tool_names = [t["function"]["name"] for t in available_tools]

        assert "book_appointment" in tool_names
        assert "initiate_payment" not in tool_names

    @patch("apps.chatbot.agent.Groq")
    def test_run_agentic_loop_json_decode_error(self, MockGroq, session):
        mock_client = MagicMock()
        MockGroq.return_value = mock_client

        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_invalid"
        mock_tool_call.function.name = "get_available_slots"
        mock_tool_call.function.arguments = "invalid_json"

        mock_choice_1 = MagicMock()
        mock_choice_1.finish_reason = "tool_calls"
        mock_choice_1.message.tool_calls = [mock_tool_call]
        mock_choice_1.message.content = None

        mock_response_1 = MagicMock()
        mock_response_1.choices = [mock_choice_1]

        mock_choice_2 = MagicMock()
        mock_choice_2.finish_reason = "stop"
        mock_choice_2.message.tool_calls = None
        mock_choice_2.message.content = "I fixed it."

        mock_response_2 = MagicMock()
        mock_response_2.choices = [mock_choice_2]

        mock_client.chat.completions.create.side_effect = [mock_response_1, mock_response_2]

        response_text = run_agentic_loop(session, "Hi")

        assert response_text == "I fixed it."
        messages = list(session.messages.order_by("timestamp"))
        assert len(messages) == 3
        assert messages[1].role == MessageRole.TOOL
        assert "invalid_arguments" in messages[1].content

    @patch("apps.chatbot.agent.execute_tool")
    @patch("apps.chatbot.agent.Groq")
    def test_run_agentic_loop_exception(self, MockGroq, mock_execute_tool, session):
        mock_client = MagicMock()
        MockGroq.return_value = mock_client

        mock_tool_call = MagicMock()
        mock_tool_call.id = "call_error"
        mock_tool_call.function.name = "get_available_slots"
        mock_tool_call.function.arguments = '{"date": "2026-08-01"}'

        mock_choice_1 = MagicMock()
        mock_choice_1.finish_reason = "tool_calls"
        mock_choice_1.message.tool_calls = [mock_tool_call]
        mock_choice_1.message.content = None

        mock_response_1 = MagicMock()
        mock_response_1.choices = [mock_choice_1]

        mock_choice_2 = MagicMock()
        mock_choice_2.finish_reason = "stop"
        mock_choice_2.message.tool_calls = None
        mock_choice_2.message.content = "I handled the error."

        mock_response_2 = MagicMock()
        mock_response_2.choices = [mock_choice_2]

        mock_client.chat.completions.create.side_effect = [mock_response_1, mock_response_2]
        mock_execute_tool.side_effect = Exception("Tool failed")

        response_text = run_agentic_loop(session, "Hi")

        assert response_text == "I handled the error."
        messages = list(session.messages.order_by("timestamp"))
        assert len(messages) == 3
        assert messages[1].role == MessageRole.TOOL
        assert "database_error_occurred" in messages[1].content
