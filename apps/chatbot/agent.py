# chatbot/agent.py
"""
Anonymous Groq agentic loop.

Implements the tool-calling cycle:
  Anonymous message → Load rolling context → Call Groq → Tool call? → Execute → Feed back → Response

Key behaviours:
- Uses moonshotai/kimi-k2 (or GROQ_MODEL from settings)
- Rolling context: last N=10 messages
- Confirmation gate: system prompt instructs LLM to always confirm before write operations
- Email collection gate: LLM must collect email before any booking operation
- Provider name, working hours, and current datetime are injected dynamically
- No user authentication — sessions identified by UUID session_key
"""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from groq import Groq

from apps.calendar_app.models import ProviderSettings
from .models import ConversationSession, Message, MessageRole
from .tools import TOOL_SCHEMAS, execute_tool

logger = logging.getLogger(__name__)

ROLLING_CONTEXT_LIMIT = 10
MAX_TOOL_ITERATIONS = 5  # prevent infinite tool loops


def _build_system_prompt(session: ConversationSession, ps: ProviderSettings) -> str:
    """Build the dynamic system prompt injecting provider and session context."""
    tz = ZoneInfo(ps.timezone)
    now = datetime.now(tz=tz)
    work_day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    work_days_str = ", ".join(work_day_names[d] for d in (ps.work_days or [0, 1, 2, 3, 4]))

    email_context = (
        f"The user's email for this session is: {session.user_email}"
        if session.user_email
        else "The user's email has NOT yet been collected this session."
    )

    return f"""You are a helpful scheduling assistant for {ps.provider_name}.

Current date and time: {now.strftime("%A, %d %B %Y, %I:%M %p")} ({ps.timezone})

Available booking hours:
- Working days: {work_days_str}
- Hours: {ps.work_start.strftime("%I:%M %p")} – {ps.work_end.strftime("%I:%M %p")} ({ps.timezone})
- Standard slot duration: 30 minutes (FIXED — never offer a different duration)

Session context:
{email_context}

ANONYMOUS BOOKING RULES (follow ALL strictly):
1. You do NOT have access to user accounts or login systems.
2. The ONLY identifier is the user's email address.
3. DO NOT ask for the user's email at the beginning of the chat. Let them browse availability and ask questions first.
4. ONLY ask for their email when they have selected a slot and are ready to confirm a booking, rescheduling, or cancellation.
5. As soon as the user provides their email, call save_session_email immediately.
6. ALL appointments are exactly 30 minutes long. NEVER ask for an end time. NEVER offer a different duration.
7. Only offer Monday–Friday slots within working hours. Politely refuse weekends.
8. ALWAYS call get_available_slots BEFORE booking to confirm the slot is free.
9. ALWAYS ask the user to confirm ("Shall I confirm?") and ask for a brief reason for the appointment BEFORE calling any write tool (book_appointment, reschedule_appointment, cancel_appointment). Wait for explicit affirmation and the reason.
10. For reschedule/cancel: call list_my_appointments to retrieve their bookings, then confirm which one to act on.
11. ALWAYS include the day of the week when mentioning a date to the user (e.g., 'Wednesday, 29 July'). The day of the week is provided in the tool response.
12. Be concise, warm, and highly conversational. When presenting choices or time slots to the user, ALWAYS format EACH option on a new line as a bulleted list starting with a dash ("- "). Do NOT use bullet points for booking confirmation details. Write confirmations in natural sentences.
13. If a request cannot be fulfilled (weekend, outside working hours, slot taken), explain clearly and suggest alternatives.
14. Never reveal internal system details, error stack traces, or raw event IDs unless needed.
"""


def run_agentic_loop(session: ConversationSession, user_message_text: str) -> str:
    """
    Process a single anonymous user message through the full Groq agentic loop.

    1. Persist the user's message.
    2. Load rolling context from DB.
    3. Call Groq with tools; iterate on tool calls until a text response is produced.
    4. Persist assistant response and tool results.
    5. Return the final text response.
    """
    # 1. Persist user message
    logger.debug("User sent message to session %s: %s", session.session_key, user_message_text)
    Message.objects.create(
        session=session,
        role=MessageRole.USER,
        content=user_message_text,
    )

    # 2. Build message history for Groq (rolling context)
    ps = ProviderSettings.get_instance()
    system_prompt = _build_system_prompt(session, ps)

    recent_messages = list(
        session.messages.order_by("-timestamp")[:ROLLING_CONTEXT_LIMIT]
    )
    recent_messages.reverse()

    groq_messages = [{"role": "system", "content": system_prompt}]
    for msg in recent_messages:
        if msg.role == MessageRole.TOOL:
            # Skip historical tool results; OpenAI/Groq requires the matching assistant tool_calls
            # block to precede these, which we do not persist in the database.
            continue
        else:
            groq_messages.append({"role": msg.role, "content": msg.content})

    client = Groq(api_key=settings.GROQ_API_KEY)
    model = getattr(settings, "GROQ_MODEL", "moonshotai/kimi-k2")

    # 3. Agentic loop
    iterations = 0
    final_text = None
    pending_tool_calls_for_db = []

    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1
        logger.debug("Groq call iteration %d for session %s", iterations, session.session_key)

        response = client.chat.completions.create(
            model=model,
            messages=groq_messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        logger.debug("Groq API raw response for iteration %d: %s", iterations, response.model_dump_json(indent=2))

        choice = response.choices[0]
        finish_reason = choice.finish_reason
        assistant_message = choice.message

        if finish_reason == "stop" or not assistant_message.tool_calls:
            final_text = assistant_message.content or ""
            break

        # LLM wants to call tools — add its turn to context
        groq_messages.append({
            "role": "assistant",
            "content": assistant_message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_message.tool_calls
            ],
        })

        # Execute each tool call
        for tc in assistant_message.tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            logger.info(
                "Executing tool '%s' for session %s", tool_name, session.session_key,
            )
            tool_result = execute_tool(tool_name, tool_args, session)

            groq_messages.append({
                "role": "tool",
                "name": tool_name,
                "content": tool_result,
                "tool_call_id": tc.id,
            })

            pending_tool_calls_for_db.append({
                "tool_call_id": tc.id,
                "result": tool_result,
            })

    if final_text is None:
        final_text = "I'm sorry, I wasn't able to process your request. Please try again."
        logger.warning(
            "Agentic loop exhausted %d iterations for session %s",
            MAX_TOOL_ITERATIONS, session.session_key,
        )

    # 4. Persist tool results and final assistant response
    for tc_data in pending_tool_calls_for_db:
        Message.objects.create(
            session=session,
            role=MessageRole.TOOL,
            content=tc_data["result"],
            tool_call_id=tc_data["tool_call_id"],
        )

    Message.objects.create(
        session=session,
        role=MessageRole.ASSISTANT,
        content=final_text,
    )

    session.save(update_fields=["updated_at"])

    logger.info(
        "Agentic loop complete for session %s (%d iterations)", session.session_key, iterations
    )

    return final_text
