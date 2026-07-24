# Dashboard App Overview

> **Namespace:** `apps.dashboard`
> **Purpose:** Provides analytical and schedule overview endpoints for authenticated doctors/providers.

---

## 1. Core Responsibilities

The `dashboard` app aggregates data from `calendar_app` to give providers a high-level view of their schedules. It follows the decoupled Service/Selector pattern and operates purely on read-only queries.

---

## 2. Models

The `dashboard` app does not define any models of its own. It relies on the `apps.calendar_app.models.Booking` model to fetch data.

---

## 3. Services and Selectors

- **`DashboardSelector`**: A selector class providing optimized queries for retrieving dashboard data.
  - `get_appointments(provider_id, date_str)`: Retrieves all bookings for a provider, optionally filtered by a specific date.
  - `get_stats(provider_id)`: Retrieves aggregated statistics for a provider (total, today, upcoming, and cancelled appointments).

---

## 4. Endpoints & Views

All endpoints require JWT Authentication and return data wrapped in `ApiResponse`.

| Endpoint | Method | Action |
|----------|--------|--------|
| `/api/v1/dashboard/appointments/` | `GET` | Returns a list of appointments for the authenticated provider. Supports `?date=YYYY-MM-DD` filtering. |
| `/api/v1/dashboard/stats/` | `GET` | Returns aggregated statistics for the authenticated provider. |

Example Response for `/api/v1/dashboard/stats/`:
```json
{
    "success": true,
    "message": "",
    "data": {
        "total": 50,
        "today": 5,
        "upcoming": 15,
        "cancelled": 2
    }
}
```
