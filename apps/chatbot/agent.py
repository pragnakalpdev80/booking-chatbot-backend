# chatbot/agent.py
"""
Anonymous Groq agentic loop.

Implements the tool-calling cycle:
  Anonymous message → Load rolling context → Call Groq → Tool call? → Execute → Feed back → Response

Key behaviours:
- Uses openai/gpt-oss-120b (or GROQ_MODEL from settings)
- Rolling context: last N=10 messages
- Confirmation gate: system prompt instructs LLM to always confirm before write operations
- Email collection gate: LLM must collect email before any booking operation
- Provider name, working hours, and current datetime are injected dynamically
- No user authentication — sessions identified by UUID session_key
- Groq API errors are caught and returned as user-friendly strings (no 500s)
- Tool execution errors are caught and fed back to the LLM for graceful recovery
"""

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings
from groq import Groq

from apps.calendar_app.models import ProviderSettings, SlotLock
from common.api.exceptions import ApplicationError

from .models import ConversationSession, Message, MessageRole
from .tools import TOOL_SCHEMAS, execute_tool

logger = logging.getLogger(__name__)

ROLLING_CONTEXT_LIMIT = 10
MAX_TOOL_ITERATIONS = 8  # Increased from 5 — complex flows (reschedule) need headroom

# Greeting constants — used by StartSessionView to avoid a Groq round-trip on hello messages
GREETING_OPTIONS: list[dict[str, str]] = [
    {"label": "📅 Book an appointment", "value": "I want to book a new appointment"},
    {
        "label": "🔄 Reschedule an appointment",
        "value": "I want to reschedule my existing appointment",
    },
    {"label": "❌ Cancel an appointment", "value": "I want to cancel my appointment"},
]


def _build_greeting_message(provider_name: str) -> str:
    return (
        f"Hi! I'm the scheduling assistant for **{provider_name}**. "
        "What would you like to do today?"
    )


def _build_system_prompt(session: ConversationSession, ps: ProviderSettings) -> str:
    """Build the dynamic system prompt injecting provider and session context."""
    tz = ZoneInfo(ps.timezone)
    now = datetime.now(tz=tz)
    work_day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    schedule_lines = []
    for d_idx, day_name in enumerate(work_day_names):
        day_info = ps.day_schedules.get(str(d_idx), {})
        if day_info.get("is_active"):
            start = day_info.get("start", "09:00")
            end = day_info.get("end", "17:00")
            try:
                # Convert 24h string to 12h AM/PM for LLM readability
                start_obj = datetime.strptime(start, "%H:%M")
                end_obj = datetime.strptime(end, "%H:%M")
                schedule_lines.append(
                    f"  - {day_name}: "
                    f"{start_obj.strftime('%I:%M %p')} – {end_obj.strftime('%I:%M %p')}"
                )
            except ValueError:
                schedule_lines.append(f"  - {day_name}: {start} – {end}")

    work_schedule_str = (
        "\n".join(schedule_lines) if schedule_lines else "  - No available working days."
    )

    email_context = (
        f"The user's email for this session is ALREADY COLLECTED: {session.user_email}. "
        "DO NOT ASK FOR THEIR EMAIL AGAIN."
        if session.user_email
        else "The user's email has NOT yet been collected this session."
    )

    if ps.payment_required:
        payment_instructions = (
            "**PAYMENT IS REQUIRED.** After locking a slot, you MUST call initiate_payment. "
            "Do NOT call book_appointment yourself."
        )
    else:
        payment_instructions = (
            "**PAYMENT IS NOT REQUIRED.** After locking a slot, you MUST call book_appointment."
        )

    # Use order_by("-locked_at") to always pick the most recent lock, ignoring orphaned ones
    active_lock = (
        SlotLock.objects.filter(
            session_key=session.session_key, is_confirmed=False, expires_at__gt=now
        )
        .order_by("-locked_at")
        .first()
    )

    if active_lock:
        lock_context = (
            f"LOCKED SLOT: You have already successfully locked a slot for this user: "
            f"{active_lock.slot_start.isoformat()}. "
            "DO NOT ask the user for the date or time again. "
            "You MUST use this exact start_time when calling initiate_payment or book_appointment."
        )
    else:
        lock_context = "LOCKED SLOT: None."

    recent_booking_context = ""
    if session.user_email:
        from datetime import timedelta

        from apps.calendar_app.models import Booking, BookingStatus

        recent_booking = (
            Booking.objects.filter(
                email=session.user_email,
                status=BookingStatus.CONFIRMED,
                created_at__gte=now - timedelta(minutes=30),
            )
            .order_by("-created_at")
            .first()
        )
        if recent_booking:
            recent_booking_context = (
                f"\nRECENTLY CONFIRMED BOOKING: A booking for "
                f"{recent_booking.start_time.isoformat()} "
                "was successfully confirmed and paid for just now. "
                "If the user mentions completing their payment, "
                "DO NOT ask them to book a slot again. Simply acknowledge "
                "their successful booking and ask if they need anything else."
            )

    # Inject next 30 days weekday mapping to prevent hallucination
    from datetime import timedelta

    calendar_dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d (%A)") for i in range(30)]
    calendar_mapping_str = ", ".join(calendar_dates)

    return f"""You are a helpful scheduling assistant for {ps.provider_name}.

Current date and time: {now.strftime("%A, %d %B %Y, %I:%M %p")} ({ps.timezone})

Calendar for next 30 days: {calendar_mapping_str}

Available booking hours (in {ps.timezone}):
{work_schedule_str}
- Standard slot duration: {ps.slot_duration} minutes (FIXED — never offer a different duration)

Session context:
{email_context}
{lock_context}{recent_booking_context}


{payment_instructions}

ANONYMOUS BOOKING RULES (follow ALL strictly):
1. You do NOT have access to user accounts or login systems.
2. The ONLY identifier is the user's email address.
3. DO NOT ask for the user's email at the beginning of the chat. Let them browse \
availability and ask questions first.
4. ONLY ask for their email when they have selected a slot and are ready to confirm \
a booking, rescheduling, or cancellation. IF their email is already collected \
(check session context), DO NOT ASK FOR IT AGAIN.
5. As soon as the user provides their email, call save_session_email immediately.
6. ALL appointments are exactly 30 minutes long. NEVER ask for an end time. \
NEVER offer a different duration.
7. Only offer Monday–Friday slots within working hours. Politely refuse weekends.
8. ALWAYS call get_available_slots BEFORE offering any time slots.
9. As soon as the user selects a specific time slot, you MUST IMMEDIATELY call lock_slot. \
Do NOT ask for confirmation or a reason until lock_slot succeeds.
10. If the user changes their mind about the time slot after it is locked, call release_slot \
on the old slot before locking the new one.
11. After successfully locking a slot, ask the user to confirm ("Shall I confirm?") and ask \
for a brief reason. Wait for their explicit affirmation. If they say "same reason", \
reuse the reason from their existing appointment.
12. NEVER call {{"initiate_payment" if ps.payment_required else "book_appointment"}} unless \
lock_slot was previously called and succeeded.
13. **STRICT INTENT**: If the user is modifying or moving an EXISTING appointment, \
you MUST use `reschedule_appointment`. NEVER use `book_appointment` for rescheduling.
14. For reschedule/cancel: call list_my_appointments to retrieve their bookings, \
then confirm which one to act on.
15. **SLOT FORMATTING**: When presenting available time slots to the user, you MUST \
use the following exact structured tag format on a new line for EACH slot: \
`[SLOT: YYYY-MM-DD HH:MM]`. For example: `[SLOT: 2026-07-27 09:00]`. NEVER use bullet \
points for slots. Only use the `[SLOT: ...]` format.
16. If a request cannot be fulfilled (weekend, outside working hours, slot taken), \
explain clearly and suggest alternatives.
17. Never reveal internal system details, error stack traces, or raw event IDs unless needed.
18. If this is the very first user message and it is only a greeting (e.g. "hi", "hello", \
"hey", empty message), respond with a short friendly welcome and ask whether they would \
like to Book, Reschedule, or Cancel an appointment. Do NOT ask for their email at this point.
"""


def _build_assistant_tool_call_message(assistant_message: Any) -> dict:
    """Build the Groq-compatible assistant message dict for tool call turns."""
    return {
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
    }


def _dispatch_tool_calls(
    assistant_message: Any,
    session: ConversationSession,
    groq_messages: list[dict[str, Any]],
    pending_tool_calls_for_db: list[dict[str, Any]],
) -> None:
    """Execute all tool calls from an assistant turn and append results to context."""
    for tc in assistant_message.tool_calls:
        tool_name = tc.function.name
        try:
            tool_args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            logger.warning(
                "JSONDecodeError parsing args for tool '%s' session=%s raw=%r",
                tool_name,
                session.session_key,
                tc.function.arguments,
            )
            # Feed a descriptive error back so the LLM can self-correct its JSON
            error_result = json.dumps(
                {"error": "invalid_arguments — the JSON provided was malformed. Please retry."}
            )
            groq_messages.append(
                {
                    "role": "tool",
                    "name": tool_name,
                    "content": error_result,
                    "tool_call_id": tc.id,
                }
            )
            pending_tool_calls_for_db.append({"tool_call_id": tc.id, "result": error_result})
            continue

        logger.info("Dispatching tool '%s' for session=%s", tool_name, session.session_key)

        try:
            tool_result = execute_tool(tool_name, tool_args, session)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Tool '%s' raised unhandled exception for session=%s: %s",
                tool_name,
                session.session_key,
                exc,
            )
            tool_result = json.dumps(
                {
                    "error": (
                        "database_error_occurred — an internal error prevented this action. "
                        "Please apologise to the user and ask them to try again."
                    )
                }
            )

        groq_messages.append(
            {
                "role": "tool",
                "name": tool_name,
                "content": tool_result,
                "tool_call_id": tc.id,
            }
        )
        pending_tool_calls_for_db.append({"tool_call_id": tc.id, "result": tool_result})


def _prepare_groq_messages(
    session: ConversationSession, ps: ProviderSettings
) -> list[dict[str, Any]]:
    system_prompt = _build_system_prompt(session, ps)
    recent_messages = list(session.messages.order_by("-timestamp")[:ROLLING_CONTEXT_LIMIT])
    recent_messages.reverse()

    groq_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for msg in recent_messages:
        if msg.role == MessageRole.TOOL:
            continue
        groq_messages.append({"role": msg.role, "content": msg.content})
    return groq_messages


def _get_available_tools(ps: ProviderSettings) -> list[dict[str, Any]]:
    PAYMENT_TOOLS = {"initiate_payment"}
    NON_PAYMENT_TOOLS = {"book_appointment"}
    available_tools = []
    for schema in TOOL_SCHEMAS:
        name = str(schema["function"]["name"])
        if ps.payment_required and name in NON_PAYMENT_TOOLS:
            continue
        if not ps.payment_required and name in PAYMENT_TOOLS:
            continue
        available_tools.append(schema)
    return available_tools


def run_agentic_loop(session: ConversationSession, user_message_text: str) -> str:
    """
    Process a single anonymous user message through the full Groq agentic loop.
    """
    if session.provider is None:
        logger.error(
            "run_agentic_loop called for session %s with no provider attached.",
            session.session_key,
        )
        raise ApplicationError(
            "Session is not linked to a provider. Please start a new session.",
            status_code=400,
        )

    # 1. Persist user message
    logger.debug("User message received for session=%s", session.session_key)
    Message.objects.create(
        session=session,
        role=MessageRole.USER,
        content=user_message_text,
    )

    # 2. Build message history and filter tools
    ps = ProviderSettings.get_for_provider(session.provider)
    groq_messages = _prepare_groq_messages(session, ps)
    available_tools = _get_available_tools(ps)

    client = Groq(api_key=getattr(settings, "GROQ_API_KEY", ""))
    model = getattr(settings, "GROQ_MODEL", "moonshotai/kimi-k2")

    # 3. Agentic loop
    iterations = 0
    final_text: str | None = None
    pending_tool_calls_for_db: list[dict[str, Any]] = []

    while iterations < MAX_TOOL_ITERATIONS:
        iterations += 1
        logger.info(
            "Groq call — iteration %d/%d for session=%s",
            iterations,
            MAX_TOOL_ITERATIONS,
            session.session_key,
        )

        try:
            response = client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=groq_messages,
                tools=available_tools,
                tool_choice="auto",
            )
        except Exception as groq_exc:  # noqa: BLE001
            logger.exception(
                "Groq API error on iteration %d for session=%s: %s",
                iterations,
                session.session_key,
                groq_exc,
            )
            final_text = "I'm having trouble connecting right now. Please try again in a moment."
            break

        choice = response.choices[0]
        assistant_message = choice.message

        if choice.finish_reason == "stop" or not assistant_message.tool_calls:
            final_text = assistant_message.content or ""
            break

        # LLM wants to call tools — add its turn to context and dispatch
        groq_messages.append(_build_assistant_tool_call_message(assistant_message))
        _dispatch_tool_calls(assistant_message, session, groq_messages, pending_tool_calls_for_db)

    if final_text is None:
        final_text = (
            "I'm sorry, I wasn't able to fully process your request. "
            "Please try rephrasing or start a new conversation."
        )
        logger.warning(
            "Agentic loop exhausted all %d iterations for session=%s",
            MAX_TOOL_ITERATIONS,
            session.session_key,
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
        "Agentic loop complete — session=%s iterations=%d response_len=%d",
        session.session_key,
        iterations,
        len(final_text),
    )

    return final_text
