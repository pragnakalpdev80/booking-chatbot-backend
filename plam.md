### **Role & Context**
You are a Staff-Level Python/Django Developer and Conversational AI Architect. I am building a chatbot-based appointment booking system using Django and the Google Calendar API. 

I need you to create a comprehensive implementation plan for a completely **anonymous booking flow** that also supports full CRUD (Create, Read, Update, Delete) operations via chat.

### **Core Business Rules**
1. **No Authentication:** Users do not need to log in or create an account in Django to use the chatbot. 
2. **Fixed Duration:** All appointments are strictly 30 minutes long. The bot should never ask for an end time.
3. **Primary Identifier (Email):** The only required user information is their email address. It is collected to finalize a booking, and it also acts as the lookup key for users wanting to check, modify, or cancel their existing appointments.
4. **Schedule Limits:** Bookings should only be offered for standard working days (Monday to Friday).

### **Conversational Flows to Support**

The chatbot must seamlessly handle these distinct user journeys:

**Flow 1: The Guided Discovery (Create - Step-by-Step)**
*   **User:** "Hello, I want to book a slot this week."
*   **Bot:** Displays available days (Monday to Friday) with their dates.
*   **User:** Chooses a date (e.g., "Wednesday").
*   **Bot:** Queries Google Calendar, finds open 30-minute blocks, presents available slots.
*   **User:** Selects a time (e.g., "10:00 AM").
*   **Bot:** "Great. To confirm your 10:00 AM slot on Wednesday, please provide your email address."
*   **User:** Provides email (`user@example.com`).
*   **Bot:** Books the slot via Google Calendar API, sends the invite, and replies with confirmation.

**Flow 2: The Direct Request (Create - One-Shot)**
*   **User:** "I want to book a slot on July 25th at 3:00 PM."
*   **Bot:** Parses the date/time and checks Google Calendar for conflicts.
*   **Bot (If available):** "That slot is available! Please provide your email address to confirm."
*   **Bot (If unavailable):** "I'm sorry, 3:00 PM is taken. Here are some other available times..."
*   **User:** Provides email.
*   **Bot:** Finalizes the booking and confirms.

**Flow 3: Checking Bookings (Read)**
*   **User:** "I want to check my bookings." / "When is my appointment?"
*   **Bot:** "Sure, please provide the email address you used to book."
*   **User:** Provides email.
*   **Bot:** Retrieves and displays upcoming appointments associated with that email.

**Flow 4: Modifications & Cancellations (Update/Delete)**
*   **User:** "I need to change my appointment to Thursday at 2 PM." OR "Cancel my appointment."
*   **Bot:** Asks for the email address (if not already provided in the current session state).
*   **Bot:** Identifies the existing booking. If rescheduling, it checks availability for the new requested time.
*   **Bot:** Executes the update or deletion via the Google Calendar API and confirms with the user.

### **The Deliverables**

Please provide a highly feasible, technical plan to implement this feature. Your plan must include:

1. **State Management Strategy:** Since users are anonymous, how should we track their conversational state, selected slots, and provided email addresses across multiple HTTP requests (e.g., Django Sessions, Redis, or a state machine)?
2. **NLP/Parsing Strategy:** How should we extract dates, times, and user intents (Book, Check, Reschedule, Cancel) from natural language (e.g., utilizing an LLM, `dateparser`, spaCy)?
3. **Google Calendar CRUD Logic:** A brief explanation of how the system will query availability, create events, and handle `eventId` lookups for updates and deletions without conflicts.
4. **Edge Cases & Security:** Please identify potential edge cases yourself (e.g., handling multiple bookings for one email, timezone mismatches, or malicious users trying to cancel someone else's appointment using just their email) and propose lightweight solutions to handle them.
5. **Phased Implementation Steps:** A step-by-step roadmap to build, test, and deploy this specific chatbot CRUD flow within our DRF architecture.



# Anonymous Chatbot Booking Flow — Implementation Plan

## Background & Scope

The current system requires users to register and present a JWT token to access any booking or chat endpoint. Every `Booking` row links to a `User` FK, and `ConversationSession` does the same. The goal is to **strip all authentication requirements from the chatbot + booking flow** while keeping the admin-only Google Calendar management endpoints fully protected.

The pivot is purely architectural — the Google Calendar integration, Celery tasks, `ProviderSettings`, and Groq agentic loop stay intact. What changes is **identity**: we replace `User` FKs with an `email` field as the sole user identifier.

> [!IMPORTANT]
> The `CLAUDE.md` rule **"Never allow unauthenticated access to booking or chatbot endpoints"** directly conflicts with the new requirement. The plan below intentionally overrides this rule for the chatbot/booking surface only. Admin routes (`/api/calendar/`, `/api/admin/`) remain `IsAdminUser`.

---

## Open Questions

> [!WARNING]
> Please answer these before approving execution — they affect schema and security design.

1. **PIN verification scope**: The previous conversation introduced a lightweight PIN system for modify/cancel. Should this be kept, simplified, or dropped entirely in favour of the "just use email as the key" model?
2. **Multiple bookings per email**: Can a single email address hold more than one active (non-cancelled) booking at a time? The current schema allows it; the plan below also allows it but surfaces all of them when the user queries by email.
3. **`slot_duration` override**: The business rule says "always 30 minutes — never ask for end time." The `ProviderSettings.slot_duration` field already defaults to 30. Should the tool schema still accept a `duration_minutes` override from the LLM, or hard-code 30 everywhere?
4. **Session lifecycle**: Without a user account, anonymous sessions are identified by a UUID returned to the client. Should the frontend be responsible for persisting this UUID, or should we use Django's cookie-based session middleware to auto-track it server-side?

---

## Proposed Changes

---

### Component 1 — `apps/calendar_app` · Schema & Booking Logic

#### [MODIFY] [models.py](file:///media/pragnakalpl23/Projects/calendar-chatbot/apps/calendar_app/models.py)

Replace the `user` ForeignKey on `Booking` with an `email` field. Add a `name` field (optional) for the Google Calendar event title.

```diff
-    user = models.ForeignKey(
-        User,
-        on_delete=models.CASCADE,
-        related_name="bookings",
-        help_text="The user who made this booking.",
-    )
+    email = models.EmailField(
+        db_index=True,
+        help_text="Email address used to identify the anonymous user.",
+    )
+    name = models.CharField(
+        max_length=255,
+        blank=True,
+        default="",
+        help_text="Optional display name provided during booking.",
+    )
```

`BookingStatus` choices and all other fields remain unchanged.

#### [MODIFY] [views.py](file:///media/pragnakalpl23/Projects/calendar-chatbot/apps/calendar_app/views.py)

- `AvailabilityView` → change `permission_classes` from `[IsAuthenticated]` to `[AllowAny]`
- `BookAppointmentView` → `[AllowAny]`; accept `email` in payload instead of reading from `request.user`
- `MyBookingsView` → rename to `BookingsByEmailView`; accept `?email=` query param; `[AllowAny]`
- `RescheduleAppointmentView` → `[AllowAny]`; ownership check becomes `Booking.objects.get(google_event_id=event_id, email=email)`
- `CancelAppointmentView` → same pattern
- Event body `summary` becomes `f"Appointment: {name or email}"`; `attendees` becomes `[{"email": email}]`

#### [MODIFY] [serializers.py](file:///media/pragnakalpl23/Projects/calendar-chatbot/apps/calendar_app/serializers.py)

- `BookAppointmentSerializer`: remove `user` field; add `email = serializers.EmailField()` and `name = serializers.CharField(required=False)`
- `BookingSerializer`: swap `username` field for `email` + `name`
- `RescheduleSerializer`: add `email = serializers.EmailField()` for ownership verification

#### New migration

```
python manage.py makemigrations calendar_app --name="replace_user_fk_with_email_on_booking"
python manage.py migrate
```

> [!CAUTION]
> This is a **breaking migration** on `Booking`. Any existing booking rows with `user_id` will need a data migration to populate `email` before the `user` column is dropped. Add a `RunPython` step that sets `email = booking.user.email` for all existing rows.

---

### Component 2 — `apps/chatbot` · Anonymous Sessions & Agent

#### [MODIFY] [models.py](file:///media/pragnakalpl23/Projects/calendar-chatbot/apps/chatbot/models.py)

Replace `user` FK with two nullable fields — an anonymous `session_key` (UUID) and an optional `email` collected during conversation:

```diff
-    user = models.ForeignKey(
-        User,
-        on_delete=models.CASCADE,
-        related_name="chat_sessions",
-    )
+    session_key = models.UUIDField(
+        default=uuid.uuid4,
+        unique=True,
+        editable=False,
+        help_text="Client-side session identifier — returned on session creation.",
+    )
+    user_email = models.EmailField(
+        blank=True,
+        default="",
+        db_index=True,
+        help_text="Email collected mid-conversation; used as lookup key for CRUD ops.",
+    )
+    # Conversational state machine field
+    intent = models.CharField(
+        max_length=50,
+        blank=True,
+        default="",
+        help_text="Current detected intent: book|check|reschedule|cancel|none",
+    )
+    pending_slot = models.JSONField(
+        null=True,
+        blank=True,
+        help_text="Temporarily holds {start, end} while awaiting email confirmation.",
+    )
```

This gives the agent structured state without Redis, using the existing DB session row.

#### [MODIFY] [views.py](file:///media/pragnakalpl23/Projects/calendar-chatbot/apps/chatbot/views.py)

All four views change `permission_classes` to `[AllowAny]`.

- `StartSessionView.post`: no longer calls `ConversationSession.objects.create(user=request.user)` — creates without a user, returns `session_id` (the UUID).
- `SendMessageView.post`: fetches session by `session_id` UUID only (no user filter).
- `SessionHistoryView.get` and `DeleteSessionView.delete`: same — filter by UUID only.

#### [MODIFY] [agent.py](file:///media/pragnakalpl23/Projects/calendar-chatbot/apps/chatbot/agent.py)

**Signature change** — `run_agentic_loop(session, user_message_text)` drops the `user` parameter.

**System prompt** (`_build_system_prompt`) no longer references `user.get_full_name()`. Instead it injects:
- `session.user_email` if already collected, else `"a user"`
- The full anonymous booking rules (see below)

**New system prompt rules to inject:**
```
ANONYMOUS BOOKING RULES (follow strictly):
1. You do NOT have access to user accounts or login systems.
2. The ONLY identifier you collect is the user's email address.
3. For any booking action (create/check/reschedule/cancel), you MUST collect the email address FIRST.
4. ALL appointments are exactly 30 minutes long. Never ask for or accept a different duration.
5. Only offer Monday–Friday slots within working hours.
6. Before any write operation, ask "Shall I confirm?" and wait for affirmation.
7. When the user provides an email, store it using the save_session_email tool immediately.
8. For reschedule/cancel: after collecting email, retrieve their booking(s) with list_my_appointments, then confirm which one to act on.
```

**Tool execution** — change `execute_tool(tool_name, tool_args, user)` to `execute_tool(tool_name, tool_args, session)`. Tools that need an email read from `session.user_email` (or from a `email` arg passed by the LLM).

#### [MODIFY] [tools.py](file:///media/pragnakalpl23/Projects/calendar-chatbot/apps/chatbot/tools.py)

**Tool signature changes**: every tool that previously accepted `user: User` now accepts `session: ConversationSession`.

**New tool: `save_session_email`** — lets the LLM persist a collected email to the session row immediately:

```json
{
  "type": "function",
  "function": {
    "name": "save_session_email",
    "description": "Persist the user's email address to the current session so it can be used for all subsequent booking operations. Call this as soon as the user provides their email.",
    "parameters": {
      "type": "object",
      "properties": {
        "email": {
          "type": "string",
          "description": "The user's email address."
        }
      },
      "required": ["email"]
    }
  }
}
```

**Updated tool: `book_appointment`** — add `email` and `name` as explicit parameters (the LLM passes them; server validates against `session.user_email` as a consistency check):

```json
"properties": {
    "start_time":  { "type": "string" },
    "end_time":    { "type": "string", "description": "Always 30 minutes after start_time." },
    "email":       { "type": "string", "description": "The user's email (already collected)." },
    "name":        { "type": "string", "description": "User's name if provided, else omit." },
    "reason":      { "type": "string" }
}
```

**Updated tools: `reschedule_appointment` and `cancel_appointment`** — add `email` parameter used for ownership verification:

```json
"properties": {
    "event_id":    { "type": "string" },
    "email":       { "type": "string" },
    ...
}
```

**Updated tool: `list_my_appointments`** — accepts `email` param, queries `Booking.objects.filter(email=email)`.

**Hard-code 30-minute duration** in `_get_available_slots` — ignore `duration_minutes` from the LLM or always default to `ps.slot_duration` (which is 30). Remove `duration_minutes` from the schema's `required` list and ensure the implementation ignores any override > 30.

**Remove the `user` import** entirely from `tools.py`.

---

### Component 3 — URL Changes

#### [MODIFY] `apps/calendar_app/urls.py`

- `/api/appointments/mine/` → `/api/appointments/by-email/` with `?email=` param (or keep the path and change the view behaviour)

#### [MODIFY] `config/urls.py` (no path changes; only ensure anonymous endpoints are not wrapped in any global auth middleware)

---

### Component 4 — Security Layer

Since there's no authentication, the only anti-abuse controls are:

#### Email-as-key Risks & Mitigations

| Risk | Lightweight Mitigation |
|------|----------------------|
| User A cancels User B's booking by knowing their email | Add an optional 4-digit **confirmation PIN** stored on `Booking.pin` (hashed). Set during booking, required for cancel/reschedule. The LLM asks for it after collecting email. |
| Bot/spam flooding the booking endpoint | Django's `django-ratelimit` on `BookAppointmentView` — max 5 POSTs per IP per hour |
| Email harvesting via listing endpoint | `BookingsByEmailView` returns only future bookings; no personal data beyond time + status |
| Fake email injection | Validate email format in serializer; no ownership proof required (trade-off accepted) |

#### [NEW] `apps/calendar_app/utils.py`

```python
import hashlib, secrets

def generate_pin() -> str:
    """Generate a 4-digit numeric PIN."""
    return str(secrets.randbelow(9000) + 1000)

def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def verify_pin(raw_pin: str, hashed_pin: str) -> bool:
    return hashlib.sha256(raw_pin.encode()).hexdigest() == hashed_pin
```

`Booking` model gains two new optional fields:
```python
pin_hash = models.CharField(max_length=64, blank=True, default="")
```

The `book_appointment` tool generates a PIN, hashes it, stores it on the `Booking`, and returns the **raw PIN** in the tool response so Groq can relay it to the user: *"Your confirmation PIN is 4821. You'll need this to reschedule or cancel."*

The `cancel_appointment` and `reschedule_appointment` tools accept a `pin` parameter and call `verify_pin()` before proceeding.

---

## 1. State Management Strategy

**Mechanism: DB-backed session row + Django Sessions (cookie fallback)**

The `ConversationSession` model *is* the state machine. No Redis needed for conversational state. The `session_key` UUID is returned on session creation and sent by the client on every subsequent message. The session row stores:

| Field | Purpose |
|-------|---------|
| `session_key` | Client-provided identifier (UUID) |
| `user_email` | Collected email — persisted via `save_session_email` tool |
| `intent` | Detected high-level intent (book/check/reschedule/cancel) |
| `pending_slot` | `{"start": "...", "end": "..."}` awaiting confirmation |

**Why not Redis?** Redis adds operational complexity. Since we're already hitting the DB for message history on every turn, a single extra column read is negligible. Redis is appropriate for distributed deployments; this is a single-server system.

**Session expiry**: Add `expires_at = models.DateTimeField(null=True)` on `ConversationSession`, set to `now + 2 hours` on creation. A periodic Celery beat task purges expired sessions weekly.

---

## 2. NLP / Parsing Strategy

**Primary: Groq tool-calling (existing architecture, enhanced schemas)**

No additional NLP library (spaCy, dateparser) is needed. The `moonshotai/kimi-k2` model already handles:
- Date extraction: "next Wednesday", "July 25th", "tomorrow" → ISO date
- Time extraction: "3 PM", "10:30", "morning" → time component
- Intent classification: "cancel", "change my appointment", "check bookings" → which tool to call

**What we add to the system prompt** to improve accuracy:
```
Today's date is {today}. The current year is {year}.
When the user says "this week", interpret it relative to today.
When a date is ambiguous, pick the nearest future occurrence.
Always convert times to {ps.timezone} timezone before passing to tools.
```

**Fallback**: If the LLM fails to extract a date (returns a tool call with a malformed date), the tool returns `{"error": "Invalid date format"}` — Groq re-prompts the user for clarification on the next iteration. This is already implemented in `_get_available_slots`.

---

## 3. Google Calendar CRUD Logic

No changes to the core Google API calls. The mapping is:

| Operation | Google API Call | Ownership Check |
|-----------|----------------|-----------------|
| Create | `events().insert()` | None (new event) |
| Read (availability) | `freebusy().query()` | None |
| Read (user's bookings) | Local DB query on `Booking.email` | Email match |
| Update | `events().patch()` | `Booking.objects.get(google_event_id=X, email=Y)` |
| Delete | `events().delete()` + set `status='cancelled'` | Same |

**`eventId` lookup for updates/deletes**: The `list_my_appointments` tool returns `google_event_id` for each booking. The LLM stores this in its context window and passes it to `reschedule_appointment` / `cancel_appointment`. The user never needs to type an event ID — the LLM manages this internally.

**Double-booking prevention**: The mandatory `_check_freebusy()` call before `events().insert()` is unchanged. This is the non-negotiable guard (per `CLAUDE.md §2.3`).

**Async writes**: Per `CLAUDE.md §2.5`, `events.patch` and `events.delete` remain Celery tasks. `events.insert` stays synchronous in the tool executor (needed to return `google_event_id` immediately to the LLM to relay to the user).

---

## 4. Edge Cases & Security

| Edge Case | Detection | Resolution |
|-----------|-----------|------------|
| User has multiple active bookings under one email | `list_my_appointments` returns all of them | Bot lists them and asks "Which one? (1 or 2)" |
| User provides wrong/misspelled email | No bookings found | "No bookings found for that email. Double-check and try again." |
| Slot requested is in the past | Compare `start_time` to `now` in tool | Return `{"error": "Cannot book a slot in the past."}` |
| Weekend or holiday requested | `weekday() not in ps.work_days` check (existing) | Bot explains and shows next available weekday |
| Timezone mismatch (user in UTC+5:30, slot shown in UTC) | All slots returned with full ISO offset | System prompt instructs LLM to display times in provider timezone |
| Malicious cancel by email guessing | PIN verification on cancel/reschedule | Without correct PIN, operation is rejected |
| Bot asks for email on every message | `session.user_email` already populated | System prompt: "If session already has an email, do NOT ask again" |
| `get_available_slots` called with no slots free | Empty `available_slots` list | LLM suggests adjacent dates automatically |
| Google API downtime | `HttpError` caught → `{"error": "..."}` in tool result | LLM informs user, suggests retry |
| Concurrent double-booking race condition | `freebusy()` check is synchronous immediately before `insert()` | Window is ~200ms; acceptable for a single-admin-calendar system |
| Expired conversation session | `expires_at` field checked in `SendMessageView` | Return `410 Gone` with "Session expired. Start a new chat." |
| LLM hallucinates an event_id | `Booking.objects.get()` raises `DoesNotExist` | Tool returns error; LLM calls `list_my_appointments` first to get real IDs |

---

## 5. Phased Implementation Roadmap

### Phase 1 — Schema Migration (Day 1, ~3 hours)
- [ ] Add `email`, `name`, `pin_hash` fields to `Booking`; remove `user` FK (with data migration)
- [ ] Add `session_key`, `user_email`, `intent`, `pending_slot`, `expires_at` to `ConversationSession`; remove `user` FK
- [ ] Generate and test migration: `makemigrations` + `migrate`
- [ ] Update `BookingSerializer`, `BookAppointmentSerializer`, `RescheduleSerializer`
- [ ] Update `admin.py` for both models (new `list_display` fields)
- **Verify**: `python manage.py check` passes; Django admin shows updated models

### Phase 2 — API Endpoint Refactor (Day 1–2, ~4 hours)
- [ ] Change `AvailabilityView`, `BookAppointmentView`, `BookingsByEmailView`, `RescheduleAppointmentView`, `CancelAppointmentView` to `AllowAny`
- [ ] Update booking creation logic: accept `email`/`name` from payload, generate PIN, return PIN in response
- [ ] Add `verify_pin()` guard to reschedule and cancel views
- [ ] Add `django-ratelimit` to `BookAppointmentView` (5/hour/IP)
- [ ] Update `MyBookingsView` → `BookingsByEmailView` with `?email=` param
- **Verify**: cURL tests against all 5 endpoints without any `Authorization` header

### Phase 3 — Chatbot Layer Refactor (Day 2, ~5 hours)
- [ ] Update `ConversationSession.objects.create()` call in `StartSessionView` (no user arg)
- [ ] Update all session lookups in views to filter by `session_key` UUID only
- [ ] Change `run_agentic_loop` signature; update system prompt with anonymous rules
- [ ] Add `save_session_email` tool schema + executor
- [ ] Update `book_appointment`, `reschedule_appointment`, `cancel_appointment`, `list_my_appointments` tool schemas to accept/use `email` parameter
- [ ] Update `execute_tool` to accept `session` instead of `user`
- [ ] Hard-lock slot duration to 30 minutes in `_get_available_slots`
- [ ] Add PIN collection step: `book_appointment` tool generates PIN, bot relays it to user; cancel/reschedule tools accept + verify PIN
- **Verify**: Run full 4-flow conversation manually via cURL

### Phase 4 — Testing (Day 3, ~4 hours)
Test files in `apps/chatbot/tests/` and `apps/calendar_app/tests/`:

| Test | File | Coverage Target |
|------|------|----------------|
| Anonymous session creation | `test_views.py` | `201` returned, no auth required |
| Full booking conversation (6 turns) | `test_agent.py` | Mock Groq + Google; assert `Booking` created with correct email |
| `save_session_email` tool | `test_tools.py` | Session row updated; email matches |
| Cancel with wrong PIN | `test_tools.py` | Returns `{"error": "Invalid PIN"}` |
| Cancel with correct PIN | `test_tools.py` | `Booking.status == 'cancelled'` |
| Weekend slot rejection | `test_tools.py` | Returns closed-day message |
| Multiple bookings for same email | `test_tools.py` | `list_my_appointments` returns all |
| Availability endpoint — no auth | `test_views.py` | `200` without token |
| Session expiry | `test_views.py` | Expired session returns `410` |
| Rate limiting | `test_views.py` | 6th booking attempt in 1h returns `429` |

### Phase 5 — Documentation & Context Update (Day 3, ~1 hour)
- [ ] Update `context/overview.md` — change Actor Model table (remove "Registered Django User" row; add "Anonymous User (email-identified)" row)
- [ ] Update `context/chatbot/overview.md` — new model fields, new tool, updated system prompt rules
- [ ] Update `context/calendar_app/overview.md` — new `Booking` schema, new `BookingsByEmailView`
- [ ] Update `API_HANDBOOK.md` — replace all JWT-auth examples for booking/chat with no-auth cURL commands; add PIN section
- [ ] Update `CLAUDE.md §1.2` — reflect the anonymous chatbot exception

---

## Verification Plan

### Automated
```bash
# Run full test suite
DJANGO_SETTINGS_MODULE=config.settings.local pytest apps/ -v --cov=apps --cov-report=term-missing

# Target: ≥85% coverage on calendar_app and chatbot
```

### Manual End-to-End (cURL — no tokens needed)
```bash
BASE="http://localhost:8000"

# 1. Start anonymous session
SESSION=$(curl -s -X POST "$BASE/api/chat/sessions/" | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# 2. Guided discovery flow
curl -s -X POST "$BASE/api/chat/message/" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION\",\"message\":\"I want to book a slot this week\"}"

# 3. Direct booking flow
curl -s -X POST "$BASE/api/chat/message/" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION\",\"message\":\"Book July 25 at 10 AM\"}"

# 4. Check bookings
curl -s "$BASE/api/appointments/by-email/?email=user@example.com"

# 5. Cancel with PIN
curl -s -X POST "$BASE/api/chat/message/" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION\",\"message\":\"Cancel my appointment\"}"
```

### Admin Routes Remain Protected
```bash
# Must still return 401/403
curl -s "$BASE/api/calendar/events/"           # expect 401
curl -s "$BASE/api/admin/provider-settings/"   # expect 401
```
