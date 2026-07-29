# Context — `apps/calendar_app/`

## Purpose

The `calendar_app` operates as the primary integration layer between the internal Django system and the external Google Calendar API. It enforces the architectural rule that **Google Calendar is the single source of truth** for all appointment times and details. It also manages the core rules engine for provider availability (holidays, breaks, working hours) and temporary slot-locking mechanisms to prevent race conditions during booking.

## Key Models (`models.py`)

- `GoogleCredential`: A single-row table storing the encrypted OAuth token (via `django-fernet-fields`) for the provider. Only the provider's token is stored here.
- `ProviderSettings`: A singleton per provider that stores core settings like `timezone`, `day_schedules`, `slot_duration`, and whether a `payment_required` deposit is active.
- `BreakTime` and `Holiday`: Relational rules associated with a `ProviderSettings` object that block out time availability.
- `Booking`: A lightweight reference table linking a Google Calendar event ID to the anonymous user's email. Live event details are parsed dynamically from Google, but the local table allows the system to easily search and retrieve a user's past bookings without heavy external querying.
- `SlotLock`: A temporary lock table. It holds a 30-minute slot open for a specific `session_key` while the user confirms their intent or completes payment, preventing double-booking.

## Key Endpoints (`/api/`)

### Calendar / OAuth (Admin only)
- `GET /calendar/login/` — Initiates Google OAuth consent flow.
- `GET /calendar/oauth2callback/` — Callback to save and encrypt OAuth token.

### Anonymous Booking (Public)
- `GET /calendar/availability/` — Queries Google's `freebusy` API + local rules to find open slots.
- `POST /appointments/book/` — Inserts an event to Google Calendar asynchronously and creates a local `Booking`.
- `GET /appointments/by-email/` — Lists local `Booking` records for an anonymous user.
- `PATCH /appointments/<event_id>/reschedule/` — Async reschedule on Google Calendar.
- `DELETE /appointments/<event_id>/cancel/` — Async cancellation on Google Calendar.

### Admin Settings
- `PATCH /admin/provider-settings/` — Updates provider schedule.
- `PUT /admin/provider-settings/breaks/` — Replaces break schedules.
- `PUT /admin/provider-settings/holidays/` — Replaces upcoming holidays.
- `GET /admin/my-calendars/` — Retrieves Google Calendars available on the connected account.

## Design Decisions

- **Asynchronous External Writes**: All write operations to Google Calendar are routed through Celery tasks (`insert_google_calendar_event`, `patch_...`, `delete_...`) to ensure fast HTTP responses.
- **Availability Enforcement**: Before booking, the `AvailabilitySelector` rigorously checks local slot-locks, local holidays/breaks, and live Google `freebusy` data.
- **Provider-Scoped Slot Locking**: All `SlotLock` and `Booking` guard queries in `_lock_slot()` are scoped to `provider=session.provider`. A lock or confirmed booking under provider A does NOT block provider B from locking the same time slot — each provider's calendar is fully independent.
- **Dependency Isolation**: `SlotLock` uses a soft `session_key` UUID instead of a direct foreign key to `ConversationSession` (which lives in the `chatbot` app) to prevent circular module dependencies.
