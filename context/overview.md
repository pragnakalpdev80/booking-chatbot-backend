# Project Context

## Purpose
A multi-tenant appointment scheduling chatbot leveraging Google Calendar.

## Architecture
- Django + DRF backend.
- PostgreSQL + Redis.
- React/Next frontend (not in this repo).

## Core Apps
- `accounts`: Doctor authentication and profile management.
- `calendar_app`: Google Calendar OAuth, availability, and bookings.
- `chatbot`: Groq AI agent for patient chat and scheduling.
- `dashboard`: Doctor dashboard endpoints for analytics and schedule overview.

## Enforced Conventions
- Views return `ApiResponse`.
- Business logic lives in `services/`.
- Reads via `selectors/`.
