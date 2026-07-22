# CLAUDE.md — Developer Rules for AI-Assisted Development

> These rules are **mandatory** and must be followed in every interaction on this project,
> without exception. They exist to maintain architectural consistency, security, and
> production-level code quality.

---

## 0. Before Writing Any Code

1. **Always read `context/overview.md`** to understand the system architecture, actor model, and data flow.
2. **Always read `context/calendar_app/overview.md`** to understand existing models, views, serializers, and planned app structures.
3. If a new app is being added, check whether a stub for it already exists in `context/calendar_app/overview.md` before designing it from scratch.

---

## 1. Architecture Rules

### 1.1 Single-Provider System
- `GoogleCredential` is a **single-row table**. Only the doctor/admin's OAuth token is ever stored here.
- **Never** create a `GoogleCredential` per patient or per request.
- All Google Calendar API calls use the single provider credential retrieved via `get_provider_credentials()` from `calendar_app`.

### 1.2 Patient Identity
- Patients are authenticated **Django `User` instances**.
- Patients must present a valid **JWT token** (`Authorization: Bearer <token>`) to access any booking or chat endpoint.
- Anonymous access is PERMITTED for chatbot and booking endpoints (`/api/chat/`, `/api/appointments/`). Admin and OAuth endpoints (`/api/calendar/`, `/api/admin/`) remain `IsAdminUser` only.

### 1.3 App Structure
- New features go into their own **dedicated Django app** (e.g., `chatbot`, `appointments`, `accounts`).
- Never add unrelated logic to `calendar_app`. Its only job is Google Calendar integration.
- New apps must be added to `INSTALLED_APPS` in `config/settings.py`.
- New apps must have their `urls.py` included in `config/urls.py` under the `/api/` prefix.

---

## 2. Google API Rules

### 2.1 Credential Access
- Always use the shared `get_provider_credentials()` utility from `calendar_app`.
- Never instantiate `Flow` or `Credentials` objects outside of `calendar_app/views.py` or `calendar_app/services.py`.

### 2.2 Token Refresh
- After every token refresh, immediately save the updated token back to `GoogleCredential`:
  ```python
  gc.token = creds.to_json()
  gc.save()
  ```
- Never discard a refreshed token without saving it.

### 2.3 Availability Before Booking
- **Always** call the Google Calendar `freebusy` API before calling `events.insert()`.
- A booking must be rejected if a conflict is detected in the `freebusy` response.
- This check is non-negotiable — it prevents double-booking.

### 2.4 Scope
- The required OAuth scope is `https://www.googleapis.com/auth/calendar` (full read/write).
- Never use `calendar.readonly` for any endpoint that needs to create, update, or delete events.

### 2.5 Async Writes
- All Google Calendar **write** operations (`events.insert`, `events.patch`, `events.delete`) must be executed via a **Celery task**.
- Read operations (`events.list`, `freebusy`) may be synchronous.

---

## 3. Security Rules

### 3.1 Secrets
- **Never hardcode** any secret, API key, password, or token in source code.
- All secrets come from environment variables via `os.getenv()` or `django-environ`.
- The `.env` file is **never committed** to version control (enforced by `.gitignore`).

### 3.2 Token Encryption
- `GoogleCredential.token` is encrypted at rest using `django-fernet-fields`.
- Never log, print, or expose the raw token value.
- The `FERNET_KEY` env var must be set in all environments.

### 3.3 Production Flags
- `OAUTHLIB_INSECURE_TRANSPORT=1` is **only** permitted in local development (`.env`).
- It must never appear in staging or production environment variables.
- `DEBUG=False` in all non-local environments.

### 3.4 Logging
- Never log: OAuth tokens, JWT tokens, passwords, patient PII (name, email, phone).
- Use structured JSON logging in production.
- Log Google API errors at `ERROR` level with the error code but **not** the full request body if it contains patient data.

---

## 4. Django Code Standards

### 4.1 Views
- All views must be **class-based** using DRF's `APIView` or `ViewSet`.
- No function-based views.
- Every view must explicitly declare `permission_classes` — never rely on global defaults alone.

### 4.2 Models
- Every new model requires a **migration** generated with `python manage.py makemigrations` before use.
- Use `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'` (set in settings).
- All models must be registered in `admin.py` with appropriate `list_display` and `readonly_fields`.

### 4.3 Serializers
- Use dedicated serializers for create, update, and read operations — never reuse a single serializer for all three.
- Validate all datetime fields as ISO 8601 with timezone.
- Enforce `start < end` in booking serializers.

### 4.4 URLs
- All endpoints must be under `/api/`.
- URL names must follow the pattern `<app>_<resource>_<action>` (e.g., `appointments_booking_create`).

### 4.5 Error Handling
- Return structured error responses: `{"error": "...", "code": "..."}`.
- Google `HttpError` must be caught and returned as `502 Bad Gateway`.
- `GoogleCredential.DoesNotExist` must be caught and returned as `400 Bad Request` with `"Google account not connected"`.

---

## 5. LLM / Chatbot Rules

### 5.1 Provider
- The LLM provider is **Groq only**.
- Use `GROQ_API_KEY` from environment.
- Model: `moonshotai/kimi-k2` (verify exact ID from Groq docs before use).
- **Do not** introduce `openai`, `anthropic`, or `google.generativeai` SDKs.

### 5.2 Tool Execution
- Tools are defined in `chatbot/tools.py` as JSON schemas.
- Tool execution logic lives in `chatbot/tool_executor.py` — it calls the appropriate `calendar_app` or `appointments` service functions.
- The agentic loop lives in `chatbot/agent.py`.
- Never put business logic directly in views.

### 5.3 Confirmation Gate
- The system prompt must instruct Groq to **always confirm** booking details with the patient before calling any write tool (`book_appointment`, `reschedule_appointment`, `cancel_appointment`).

### 5.4 System Prompt
- Inject at runtime: `ProviderSettings.provider_name`, current datetime + timezone, working hours, and the authenticated patient's full name.
- Load `ProviderSettings` from DB — never hardcode provider details.

---

## 6. Testing Rules

- Every new view must have **at least two tests**: one happy-path and one error-path.
- Use `pytest-django` as the test runner.
- Mock all Google API calls in tests using `unittest.mock`.
- Mock all Groq API calls in tests.
- Test files live in `<app>/tests/` as a package, split by `test_views.py`, `test_models.py`, `test_serializers.py`.

---

## 7. Quick Reference

```
# Get provider credentials (use everywhere)
from calendar_app.services import get_provider_credentials
creds = get_provider_credentials()

# Build calendar service
from googleapiclient.discovery import build
service = build("calendar", "v3", credentials=creds)

# Always check availability before booking
freebusy_result = service.freebusy().query(body={...}).execute()

# All writes go through Celery
from appointments.tasks import create_calendar_event
create_calendar_event.delay(event_body)
```
