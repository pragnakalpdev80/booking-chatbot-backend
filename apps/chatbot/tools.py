# chatbot/tools.py
"""
Tool schemas and executor for the anonymous Groq agentic loop.

Six tools are available:
  1. save_session_email    — persist the user's email to the session
  2. get_available_slots   — list free 30-minute booking times
  3. book_appointment      — create a booking on the calendar
  4. reschedule_appointment — move an existing booking
  5. cancel_appointment    — cancel a booking
  6. list_my_appointments  — list bookings for an email
"""

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import OperationalError, transaction
from django.utils.timezone import now
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from apps.calendar_app.models import (
    Booking,
    BookingStatus,
    GoogleCredential,
    ProviderSettings,
    SlotLock,
)

from .models import ConversationSession

logger = logging.getLogger(__name__)

# Hard-coded business rule — never overrideable
SLOT_DURATION_MINUTES = 30

# Constant for error message used across multiple tools
_EMAIL_NOT_COLLECTED_MSG = "Email not collected yet. Please ask the user for their email first."


# ─── Tool schemas ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "save_session_email",
            "description": (
                "Persist the user's email address to the current session. "
                "Call this IMMEDIATELY when the user provides their email address, "
                "before performing any other operation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "The user's email address.",
                    },
                },
                "required": ["email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_slots",
            "description": (
                "Retrieve available (free) 30-minute time slots for a given date. "
                "Use this BEFORE booking to show the user what times are open."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": (
                            "The date to check in YYYY-MM-DD format (e.g. '2026-07-25')."
                        ),
                    },
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Book a 30-minute slot on the calendar for the user. "
                "ALWAYS obtain explicit user confirmation before calling. "
                "The user MUST have successfully locked the slot via lock_slot first. "
                "The user's email MUST already be saved in the session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "string",
                        "description": (
                            "ISO 8601 datetime string with timezone offset "
                            "(e.g. '2026-07-25T10:00:00+05:30')."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "description": "Reason for the appointment.",
                    },
                },
                "required": ["start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lock_slot",
            "description": (
                "Temporarily lock a 30-minute time slot for the user for 15 minutes. "
                "Call this IMMEDIATELY when the user selects a time, BEFORE asking them "
                "to confirm the booking or provide a reason."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "string",
                        "description": (
                            "ISO 8601 datetime string with timezone offset "
                            "(e.g. '2026-07-25T10:00:00+05:30')."
                        ),
                    },
                },
                "required": ["start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "release_slot",
            "description": (
                "Release a previously locked time slot. "
                "Call this if the user changes their mind and wants to pick a different time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_time": {
                        "type": "string",
                        "description": (
                            "ISO 8601 datetime string with timezone offset "
                            "(e.g. '2026-07-25T10:00:00+05:30')."
                        ),
                    },
                },
                "required": ["start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": (
                "Reschedule an existing 30-minute booking to a new start time. "
                "Obtain user confirmation before calling. "
                "Verify the new slot is free with get_available_slots first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": (
                            "The Google Calendar event ID of the appointment to reschedule."
                        ),
                    },
                    "new_start_time": {
                        "type": "string",
                        "description": "New start time as ISO 8601 datetime string with timezone.",
                    },
                },
                "required": ["event_id", "new_start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": (
                "Cancel an existing booking. "
                "ALWAYS ask the user to confirm before calling this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "The Google Calendar event ID of the appointment to cancel.",
                    },
                },
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_my_appointments",
            "description": "List all upcoming bookings for the user's email address.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Filter from this date (YYYY-MM-DD). Defaults to today.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": (
                            "Filter up to this date (YYYY-MM-DD). "
                            "Defaults to 30 days from start_date."
                        ),
                    },
                },
                "required": [],
            },
        },
    },
]


# ─── Tool executor ────────────────────────────────────────────────────────────


def _get_service(provider):
    try:
        credential = GoogleCredential.objects.select_related("user").get(user=provider)
    except GoogleCredential.DoesNotExist:
        raise ValueError(
            "The administrator has not linked their Google Calendar yet. "
            "Tell the user that the booking service is currently unavailable."
        ) from None
    creds = credential.get_credentials()
    return build("calendar", "v3", credentials=creds)


def _check_freebusy(service, start_dt: datetime, end_dt: datetime, calendar_id: str) -> bool:
    body = {
        "timeMin": start_dt.isoformat(),
        "timeMax": end_dt.isoformat(),
        "items": [{"id": calendar_id}],
    }
    result = service.freebusy().query(body=body).execute()
    busy = result.get("calendars", {}).get(calendar_id, {}).get("busy", [])
    return len(busy) == 0


def execute_tool(tool_name: str, tool_args: dict, session: ConversationSession) -> str:
    """
    Dispatch a tool call and return the result as a JSON string.
    All exceptions are caught and returned as error JSON so the LLM can
    surface a helpful message to the user.
    """
    try:
        if tool_name == "save_session_email":
            return _save_session_email(session, **tool_args)
        elif tool_name == "lock_slot":
            return _lock_slot(session, **tool_args)
        elif tool_name == "release_slot":
            return _release_slot(session, **tool_args)
        elif tool_name == "get_available_slots":
            return _get_available_slots(session, **tool_args)
        elif tool_name == "book_appointment":
            return _book_appointment(session, **tool_args)
        elif tool_name == "reschedule_appointment":
            return _reschedule_appointment(session, **tool_args)
        elif tool_name == "cancel_appointment":
            return _cancel_appointment(session, **tool_args)
        elif tool_name == "list_my_appointments":
            return _list_my_appointments(session, **tool_args)
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("Tool %s raised exception: %s", tool_name, exc)
        return json.dumps({"error": str(exc)})


# ─── Individual tool implementations ─────────────────────────────────────────


def _is_slot_free(busy_intervals: list, slot_start: datetime, slot_end: datetime) -> bool:
    """Return True if the slot does not overlap any busy interval."""
    for b in busy_intervals:
        b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
        if slot_start < b_end and slot_end > b_start:
            return False
    return True


def _build_no_slots_message(end_of_day: datetime, now: datetime) -> str:
    """Return a human-friendly message when no slots are available."""
    if end_of_day <= now:
        return (
            "The working hours for this date have already passed. "
            "Please ask the user to select a future date."
        )
    return (
        "All available slots for this date are fully booked. "
        "Please ask the user to select another date."
    )


def _save_session_email(session: ConversationSession, email: str) -> str:
    """Persist the provided email to the session row immediately."""
    logger.debug("Tool: save_session_email — session %s, email %s", session.session_key, email)
    session.user_email = email.strip().lower()
    session.save(update_fields=["user_email", "updated_at"])
    return json.dumps({"status": "email_saved", "email": session.user_email})


def _lock_slot(session: ConversationSession, start_time: str) -> str:
    """Temporarily reserve a slot to prevent concurrent bookings."""
    logger.debug("Tool: lock_slot — session %s, start %s", session.session_key, start_time)

    try:
        start_dt = datetime.fromisoformat(start_time)
    except ValueError:
        return json.dumps({"error": f"Invalid start_time format: {start_time}. Use ISO 8601."})

    if start_dt <= now():
        return json.dumps({"error": "Cannot lock a time slot in the past."})

    end_dt = start_dt + timedelta(minutes=SLOT_DURATION_MINUTES)

    # First, verify freebusy on Google Calendar to ensure it's actually free
    assert session.provider is not None
    service = _get_service(session.provider)
    assert session.provider is not None
    ps = ProviderSettings.get_for_provider(session.provider)
    if not _check_freebusy(service, start_dt, end_dt, ps.calendar_id):
        return json.dumps(
            {
                "error": "This slot is no longer available on the calendar. "
                "Please choose another time."
            }
        )

    try:
        with transaction.atomic():
            # Release any existing active locks held by this session (so they don't hold
            # multiple slots)
            SlotLock.objects.filter(session_key=session.session_key, is_confirmed=False).delete()

            # Delete any expired, unconfirmed locks for this specific slot to satisfy the
            # UniqueConstraint
            SlotLock.objects.filter(
                slot_start=start_dt, expires_at__lte=now(), is_confirmed=False
            ).delete()

            # Try to acquire a lock, ensuring no one else holds an active lock
            existing = (
                SlotLock.objects.select_for_update(nowait=True)
                .filter(slot_start=start_dt, is_confirmed=False)
                .first()
            )

            if existing:
                return json.dumps(
                    {
                        "error": "This slot is currently being booked by someone else. "
                        "Please select another time."
                    }
                )

            lock = SlotLock.objects.create(
                session_key=session.session_key,
                slot_start=start_dt,
                slot_end=end_dt,
                expires_at=now() + timedelta(minutes=15),
            )

    except OperationalError:
        # DB row lock could not be acquired because another transaction is currently
        # touching this slot's locks
        return json.dumps(
            {
                "error": "This slot is currently being booked by someone else. "
                "Please select another time."
            }
        )

    return json.dumps(
        {
            "status": "locked",
            "expires_at": lock.expires_at.isoformat(),
            "message": "Slot successfully locked for 15 minutes. "
            "Please proceed to ask the user to confirm.",
        }
    )


def _release_slot(session: ConversationSession, start_time: str) -> str:
    """Release a locked slot if the user changes their mind."""
    logger.debug("Tool: release_slot — session %s, start %s", session.session_key, start_time)

    try:
        start_dt = datetime.fromisoformat(start_time)
    except ValueError:
        return json.dumps({"error": f"Invalid start_time format: {start_time}."})

    deleted, _ = SlotLock.objects.filter(
        session_key=session.session_key, slot_start=start_dt, is_confirmed=False
    ).delete()

    if deleted:
        return json.dumps({"status": "released", "message": "Slot lock released."})
    else:
        return json.dumps({"status": "ignored", "message": "No active lock found for this slot."})


def _get_available_slots(session: ConversationSession, date: str) -> str:
    logger.debug("Tool: get_available_slots — session %s, date %s", session.session_key, date)
    assert session.provider is not None
    ps = ProviderSettings.get_for_provider(session.provider)

    try:
        query_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return json.dumps({"error": f"Invalid date format: {date}. Use YYYY-MM-DD."})

    tz = ZoneInfo(ps.timezone)

    # Enforce Mon–Fri
    if query_date.weekday() not in (ps.work_days or [0, 1, 2, 3, 4]):
        return json.dumps(
            {
                "available_slots": [],
                "message": "Appointments are only available Monday to Friday.",
            }
        )

    start_of_day = datetime.combine(query_date, ps.work_start, tzinfo=tz)
    end_of_day = datetime.combine(query_date, ps.work_end, tzinfo=tz)
    slot_delta = timedelta(minutes=SLOT_DURATION_MINUTES)

    assert session.provider is not None
    service = _get_service(session.provider)
    freebusy_result = (
        service.freebusy()
        .query(
            body={
                "timeMin": start_of_day.isoformat(),
                "timeMax": end_of_day.isoformat(),
                "items": [{"id": ps.calendar_id}],
            }
        )
        .execute()
    )
    logger.debug("Google API freebusy result: %s", json.dumps(freebusy_result))

    busy_intervals = freebusy_result.get("calendars", {}).get(ps.calendar_id, {}).get("busy", [])

    # Get active locks held by OTHER sessions
    active_locked_starts = set(
        SlotLock.objects.filter(
            slot_start__date=query_date,
            expires_at__gt=now(),
            is_confirmed=False,
        )
        .exclude(session_key=session.session_key)
        .values_list("slot_start", flat=True)
    )

    now_tz = datetime.now(tz=tz)
    slots = []
    current = start_of_day
    while current + slot_delta <= end_of_day:
        slot_end = current + slot_delta
        # Only offer slots that are in the future, free on Google Calendar, and not locked
        # by someone else
        if (
            current >= now_tz
            and _is_slot_free(busy_intervals, current, slot_end)
            and current not in active_locked_starts
        ):
            slots.append({"start": current.isoformat(), "end": slot_end.isoformat()})
        current = slot_end

    message = _build_no_slots_message(end_of_day, now_tz) if not slots else ""

    return json.dumps(
        {
            "date": date,
            "day_of_week": query_date.strftime("%A"),
            "timezone": ps.timezone,
            "slot_duration_minutes": SLOT_DURATION_MINUTES,
            "available_slots": slots,
            "count": len(slots),
            "message": message,
        }
    )


def _book_appointment(session: ConversationSession, start_time: str, reason: str = "") -> str:
    logger.debug("Tool: book_appointment — session %s, start %s", session.session_key, start_time)

    email = session.user_email
    if not email:
        return json.dumps({"error": _EMAIL_NOT_COLLECTED_MSG})

    try:
        start_dt = datetime.fromisoformat(start_time)
    except ValueError:
        return json.dumps({"error": f"Invalid start_time format: {start_time}. Use ISO 8601."})

    # Validate that this session holds an active lock for this slot
    lock = SlotLock.objects.filter(
        session_key=session.session_key,
        slot_start=start_dt,
        expires_at__gt=now(),
        is_confirmed=False,
    ).first()

    if not lock:
        return json.dumps(
            {
                "error": "Your reservation for this slot has expired or you haven't "
                "locked it yet. Please pick a time again."
            }
        )

    # Enforce 30-min duration always
    end_dt = start_dt + timedelta(minutes=SLOT_DURATION_MINUTES)

    assert session.provider is not None
    service = _get_service(session.provider)
    assert session.provider is not None
    ps = ProviderSettings.get_for_provider(session.provider)
    if not _check_freebusy(service, start_dt, end_dt, ps.calendar_id):
        lock.delete()
        return json.dumps({"error": "The slot is no longer available. Please pick another time."})

    event_body = {
        "summary": f"Appointment: {email}",
        "description": reason,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": ps.timezone},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": ps.timezone},
        "attendees": [{"email": email}],
    }

    try:
        created_event = (
            service.events().insert(calendarId=ps.calendar_id, body=event_body).execute()
        )
        logger.debug("Google API insert event result: %s", json.dumps(created_event))
        google_event_id = created_event["id"]

        with transaction.atomic():
            Booking.objects.create(
                email=email,
                google_event_id=google_event_id,
                start_time=start_dt,
                end_time=end_dt,
                reason=reason,
                status=BookingStatus.CONFIRMED,
            )
            # Mark the lock as confirmed so it's ignored going forward
            lock.is_confirmed = True
            lock.save(update_fields=["is_confirmed"])

    except Exception as e:
        logger.exception("Failed to book appointment or create record: %s", e)
        lock.delete()
        return json.dumps(
            {"error": "Failed to create booking on Google Calendar. Please try again."}
        )

    logger.info("Chatbot booked: email=%s event=%s", email, google_event_id)

    return json.dumps(
        {
            "status": "confirmed",
            "google_event_id": google_event_id,
            "html_link": created_event.get("htmlLink", ""),
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "email": email,
            "reason": reason,
        }
    )


def _reschedule_appointment(
    session: ConversationSession, event_id: str, new_start_time: str
) -> str:
    logger.debug(
        "Tool: reschedule_appointment — session %s, event %s", session.session_key, event_id
    )

    email = session.user_email
    if not email:
        return json.dumps({"error": _EMAIL_NOT_COLLECTED_MSG})

    try:
        booking = Booking.objects.get(google_event_id=event_id, email=email)
    except Booking.DoesNotExist:
        return json.dumps(
            {"error": f"No booking found with event ID {event_id} for email {email}."}
        )

    try:
        new_start = datetime.fromisoformat(new_start_time)
    except ValueError:
        return json.dumps({"error": f"Invalid new_start_time: {new_start_time}."})

    new_end = new_start + timedelta(minutes=SLOT_DURATION_MINUTES)

    assert session.provider is not None
    service = _get_service(session.provider)
    assert session.provider is not None
    ps = ProviderSettings.get_for_provider(session.provider)
    if not _check_freebusy(service, new_start, new_end, ps.calendar_id):
        return json.dumps({"error": "The new slot is not available. Please choose another time."})

    patch_body = {
        "start": {"dateTime": new_start.isoformat(), "timeZone": ps.timezone},
        "end": {"dateTime": new_end.isoformat(), "timeZone": ps.timezone},
    }

    updated_event = (
        service.events()
        .patch(calendarId=ps.calendar_id, eventId=event_id, body=patch_body)
        .execute()
    )
    logger.debug("Google API patch event result: %s", json.dumps(updated_event))

    booking.start_time = new_start
    booking.end_time = new_end
    booking.status = BookingStatus.RESCHEDULED
    booking.save(update_fields=["start_time", "end_time", "status", "updated_at"])

    logger.info("Chatbot rescheduled: email=%s event=%s -> %s", email, event_id, new_start_time)

    return json.dumps(
        {
            "status": "rescheduled",
            "google_event_id": event_id,
            "new_start_time": new_start.isoformat(),
            "new_end_time": new_end.isoformat(),
            "html_link": updated_event.get("htmlLink", ""),
        }
    )


def _cancel_appointment(session: ConversationSession, event_id: str) -> str:
    logger.debug("Tool: cancel_appointment — session %s, event %s", session.session_key, event_id)

    email = session.user_email
    if not email:
        return json.dumps({"error": _EMAIL_NOT_COLLECTED_MSG})

    try:
        booking = Booking.objects.get(google_event_id=event_id, email=email)
    except Booking.DoesNotExist:
        return json.dumps(
            {"error": f"No booking found with event ID {event_id} for email {email}."}
        )

    assert session.provider is not None
    service = _get_service(session.provider)
    assert session.provider is not None
    ps = ProviderSettings.get_for_provider(session.provider)
    try:
        service.events().delete(calendarId=ps.calendar_id, eventId=event_id).execute()
    except HttpError as exc:
        if exc.resp.status != 410:  # 410 = already gone, treat as success
            return json.dumps({"error": f"Google Calendar error: {exc}"})

    booking.status = BookingStatus.CANCELLED
    booking.save(update_fields=["status", "updated_at"])

    logger.info("Chatbot cancelled: email=%s event=%s", email, event_id)
    return json.dumps({"status": "cancelled", "google_event_id": event_id})


def _list_my_appointments(
    session: ConversationSession,
    start_date: str | None = None,
    end_date: str | None = None,
    **kwargs,
) -> str:
    logger.debug("Tool: list_my_appointments — session %s", session.session_key)

    email = session.user_email
    if not email:
        return json.dumps({"error": _EMAIL_NOT_COLLECTED_MSG})

    from datetime import date as date_type

    today = date_type.today()

    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d").date()
        except ValueError:
            return json.dumps({"error": f"Invalid start_date: {start_date}"})
    else:
        start = today

    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return json.dumps({"error": f"Invalid end_date: {end_date}"})
    else:
        end = start + timedelta(days=30)

    bookings = (
        Booking.objects.filter(
            email=email,
            start_time__date__gte=start,
            start_time__date__lte=end,
        )
        .exclude(status=BookingStatus.CANCELLED)
        .order_by("start_time")
    )

    assert session.provider is not None
    ps = ProviderSettings.get_for_provider(session.provider)
    tz = ZoneInfo(ps.timezone)

    result = [
        {
            "booking_id": b.pk,
            "google_event_id": b.google_event_id,
            "start_time": b.start_time.astimezone(tz).isoformat(),
            "end_time": b.end_time.astimezone(tz).isoformat(),
            "reason": b.reason,
            "status": b.status,
        }
        for b in bookings
    ]

    return json.dumps(
        {
            "email": email,
            "timezone": ps.timezone,
            "from": str(start),
            "to": str(end),
            "appointments": result,
            "count": len(result),
        }
    )
