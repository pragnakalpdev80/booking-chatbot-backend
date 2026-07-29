# Project Context — Overview

Brief, durable context for the Booking Chatbot backend. Context is **distributed**: this file covers project-wide structure and conventions; each app/feature keeps its own context file under `context/<app>/overview.md` as it is built.

## Purpose

A scalable, secure Django REST Framework backend designed to serve a dual-purpose system:
1. **Admin Portal**: Allows medical providers (doctors) to register, authenticate via JWT, configure their availability/holidays/breaks, and synchronize with their Google Calendar.
2. **Chatbot Interface**: Allows anonymous users (patients) to interact with an AI chatbot (Groq LLM) to list available slots, book appointments, reschedule, and cancel them natively via natural language.

## Structure

- `config/` — project configuration package: `settings/` split environments, `celery.py`, `urls.py`, middleware, exception handlers.
- `common/` — shared, feature-agnostic utilities: custom `ApiResponse`, standard `ApplicationError`, generic `custom_exception_handler`.
- `apps/` — feature modules:
  - `accounts`: Provider registration and JWT authentication.
  - `calendar_app`: Core Google Calendar integration, availability parsing, bookings.
  - `chatbot`: Agentic loop with Groq, managing anonymous `ConversationSession`.
  - `dashboard`: Read-only statistics and appointment listing for the admin portal.
  - `payments`: Mock payment integration for booking deposits.

## Enforced conventions (non-negotiable)

- **Class-based Views** — DRF class-based views only; no function-based views.
- **Service/Selector Layering** — Business logic is extracted from views into services (writes) and selectors (reads).
- **Asynchronous Operations** — All write operations to external services (like Google Calendar API `events.insert`) must be deferred to Celery tasks to prevent blocking HTTP requests.
- **Security-First** — Secrets are loaded from `.env`, Google OAuth tokens are encrypted at rest via `django-fernet-fields`.
- **Fail-Safe Booking** — The agentic loop must ALWAYS check `freebusy` availability right before committing a booking to prevent race conditions.

## Integrations

- **Google Calendar API**: The primary source of truth for events.
- **Groq LLM**: `moonshotai/kimi-k2` model used as the reasoning engine for the chatbot.
- **Mock Payment Gateway**: Simulates a payment flow required before a booking lock can be confirmed.
