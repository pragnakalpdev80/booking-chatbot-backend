# Booking Chatbot — Project Context

## Purpose
A multi-tenant, anonymous appointment scheduling chatbot powered by an AI agent (Groq/Kimi-K2)
integrated with Google Calendar, a mock payment gateway, and a React frontend.

## Architecture
- **Backend**: Django 5 + Django REST Framework
- **Database**: PostgreSQL (primary store) + Redis (Celery broker)
- **LLM**: Groq Cloud API — model `moonshotai/kimi-k2` (configurable via `GROQ_MODEL`)
- **Calendar**: Google Calendar API v3 (OAuth2, single admin credential)
- **Frontend**: React (Vite) — separate repo under `../frontend/`

## Core Apps

| App | Responsibility |
|-----|---------------|
| `accounts` | Provider authentication and profile management (JWT) |
| `calendar_app` | Google Calendar OAuth, freebusy queries, Booking & SlotLock models |
| `chatbot` | Groq AI agentic loop, ConversationSession & Message persistence |
| `dashboard` | Provider-facing analytics and schedule overview endpoints |
| `payments` | Mock payment gateway (Razorpay-style) with async Celery webhook handling |

## Enforced Conventions
- Views return `ApiResponse` (wraps DRF Response).
- All business logic lives in `services/`.
- Read-only queries are in `selectors/`.
- All Google Calendar writes in the payment path go through Celery (`finalize_booking_task`).

## Key Context Documents

| Document | Description |
|----------|-------------|
| [`context/chatbot/overview.md`](chatbot/overview.md) | **AI Architecture deep-dive** — agent orchestration, system prompt, tool registry, and interaction flow SOPs |
| [`context/calendar_app/`](calendar_app/) | Google Calendar integration and availability engine |
| [`context/payments/`](payments/) | Mock payment gateway design and webhook flow |
| [`context/accounts/`](accounts/) | Provider authentication architecture |
