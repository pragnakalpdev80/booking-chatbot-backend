# Calendar Chatbot — Project Overview

## Purpose

A **generic appointment booking system** where users can book, reschedule, and cancel appointments via a natural-language chatbot. The chatbot is powered by **Groq LLM** and all appointment data lives exclusively in the **admin's Google Calendar** (single source of truth).

---

## Actor Model

| Actor | Type | Role |
|-------|------|------|
| **Admin / Owner** | Django superuser | Links their Google Calendar once via OAuth; configures working hours; views all appointments via admin |
| **User** | Anonymous (Email-based) | Accesses the chatbot and booking endpoints anonymously. Identified exclusively by their email. |
| **Groq LLM** | External AI service | Parses user intent, selects the correct Calendar tool, generates natural-language responses |
| **Google Calendar API** | External service | Stores all appointment events; the only persistent appointment data store |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Web Framework | Django 6 |
| REST API | Django REST Framework (DRF) |
| Database | PostgreSQL |
| Authentication | JWT via `djangorestframework-simplejwt` |
| Google OAuth | `google-auth-oauthlib`, `google-api-python-client` |
| Calendar Data | Google Calendar API v3 |
| AI / Chatbot | Groq API — `moonshotai/kimi-k2` (120B OSS model) |
| Async Tasks | Celery + Redis (write operations) |
| Secret Management | `python-dotenv` / `django-environ` |
| Token Encryption | `django-fernet-fields` |
| Logging / Monitoring | Python `logging` (JSON) + Sentry |

---

## Architecture Diagram

```
┌────────────────────────────────────────────────────────────────┐
│                      Django Application                        │
│                                                                │
│  ┌──────────────────┐      ┌─────────────────────────────────┐ │
│  │  User            │─JWT─▶│  Groq Chatbot                   │ │
│  │  (Django User)   │      │  /api/chat/message/             │ │
│  │                  │      │                                 │ │
│  │  POST /api/      │      │  Agentic Loop:                  │ │
│  │  chat/message/   │      │  1. Load conversation history   │ │
│  └──────────────────┘      │  2. Call Groq with tool schemas │ │
│                            │  3. Execute selected tool       │ │
│  ┌──────────────────┐      │  4. Feed result back to Groq    │ │
│  │  Admin           │      │  5. Return natural-language resp│ │
│  │  (Superuser)     │      └──────────────┬──────────────────┘ │
│  │                  │                     │                    │
│  │  Links Google    │      ┌──────────────▼──────────────────┐ │
│  │  Calendar via    │      │  Calendar Service Layer         │ │
│  │  OAuth once      │      │  apps.calendar_app              │ │
│  └──────────────────┘      └──────────────┬──────────────────┘ │
│                                           │                    │
│                            ┌──────────────▼──────────────────┐ │
│                            │  GoogleCredential (DB)          │ │
│                            │  ONE record — the admin's       │ │
│                            │  encrypted OAuth token          │ │
│                            └──────────────┬──────────────────┘ │
└───────────────────────────────────────────┼────────────────────┘
                                            │
                             ┌──────────────▼──────────────────┐
                             │   Google Calendar API v3        │
                             │   (Admin's Calendar)            │
                             │   Source of truth for all       │
                             │   appointment data              │
                             └─────────────────────────────────┘
```

---

## Request Lifecycle

### User Books a Slot

```
1. User sends POST /api/chat/message/ with session_key
2. Django loads session via session_key UUID
3. Last N conversation messages loaded from DB (rolling context)
4. Groq receives: system prompt + context + user message + tool schemas
5. Groq responds with tool_call: get_available_slots(date="2026-07-25", duration=30)
6. Django calls Google Calendar freebusy API with admin's credentials
7. Free slots returned to Groq
8. Groq asks user to pick a slot
9. User confirms → Groq calls: book_appointment(start, end, reason)
10. Django runs events.insert() on admin's Google Calendar (via Celery)
11. Booking reference saved to local Booking model
12. Groq generates confirmation message → returned to user
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Single `GoogleCredential` record** | This is a single-provider system. Only the admin's calendar is ever linked. |
| **Users are Anonymous** | Frictionless booking. Bookings are tied to the email address provided during chat. |
| **Google Calendar = source of truth** | Avoids sync complexity. `Booking` model only stores a reference (event_id + status). |
| **Groq for LLM** | Fast inference, tool-calling support, `GROQ_API_KEY` already configured. |
| **Celery for write operations** | Decouples Google API latency from chat response time; enables retries. |
| **`ProviderSettings` model** | Working hours and slot duration are admin-configurable at runtime, not hardcoded. |
| **`apps/` directory structure** | Django apps are grouped in the `apps/` namespace for cleaner project root structure. |

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `True` for local, `False` for production |
| `ALLOWED_HOSTS` | Comma-separated allowed hostnames |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection |
| `GOOGLE_CLIENT_SECRETS_FILE` | Absolute path to `credentials.json` |
| `GOOGLE_OAUTH_REDIRECT_URI` | OAuth callback URL |
| `GROQ_API_KEY` | Groq API authentication |
| `FERNET_KEY` | Encryption key for `GoogleCredential.token` |
| `SENTRY_DSN` | Sentry error monitoring (optional) |
| `CELERY_BROKER_URL` | Redis URL for Celery (`redis://localhost:6379/0`) |
| `OAUTHLIB_INSECURE_TRANSPORT` | `1` in local dev only — **never in production** |

---

## URL Structure

```
/api/
├── accounts/
│   ├── register/          POST  — user self-registration
│   ├── login/             POST  — returns JWT tokens
│   ├── token/refresh/     POST  — refresh JWT
│   └── me/                GET   — own profile
│
├── calendar/
│   ├── login/             GET   — returns Google OAuth URL (admin only)
│   ├── oauth2callback/    GET   — OAuth exchange + store credential
│   ├── events/            GET   — list all appointments (admin)
│   ├── events/<id>/       GET, PATCH, DELETE — manage appointment (admin)
│   └── availability/      GET   — free slots for a given date
│
├── appointments/
│   ├── book/              POST  — book a slot (user)
│   ├── <id>/reschedule/   PATCH — move appointment (user)
│   ├── <id>/cancel/       DELETE — cancel appointment (user)
│   └── mine/              GET   — list own bookings (user)
│
├── admin/
│   └── provider-settings/ GET, PATCH — working hours config (superuser)
│
└── chat/
    ├── sessions/          POST  — start new conversation
    ├── message/           POST  — send message, get AI response
    ├── sessions/<id>/messages/ GET — full history
    └── sessions/<id>/    DELETE — end session
```
