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
  - `get_appointments(provider_id, start_date_str, end_date_str, email_str)`: Retrieves strictly `CONFIRMED` and `FUTURE` (`start_time > now`) appointments for a provider (for the overview page).
  - `get_all_appointments(provider_id, start_date_str, end_date_str, email_str)`: Retrieves all bookings for a provider ordered by `-start_time`.
  - `get_cancelled_appointments(provider_id, start_date_str, end_date_str, email_str)`: Retrieves strictly `CANCELLED` appointments for a provider ordered by `-start_time`.
  - `get_stats(provider_id)`: Retrieves aggregated statistics for a provider (total, today, upcoming, and cancelled appointments).

---

## 4. Endpoints & Views

All endpoints require JWT Authentication and return data wrapped in `ApiResponse`. For paginated endpoints, pagination metadata (`count`, `next`, `previous`, `page`, `page_size`) is included alongside the `data` key using `ApiResponse.paginated_response()`.

| Endpoint | Method | Action |
|----------|--------|--------|
| `/api/v1/dashboard/appointments/` | `GET` | Returns an unpaginated list of strictly `CONFIRMED` and `FUTURE` appointments. Supports `?start_date`, `?end_date`, and `?email`. `start_date` cannot be in the past. |
| `/api/v1/dashboard/appointments/all/` | `GET` | **Paginated** (default 10). Returns all appointments ordered descending. Supports `?start_date`, `?end_date`, and `?email` filtering. |
| `/api/v1/dashboard/appointments/cancelled/` | `GET` | **Paginated** (default 10). Returns only cancelled appointments ordered descending. Supports `?start_date`, `?end_date`, and `?email` filtering. |
| `/api/v1/dashboard/stats/` | `GET` | Returns aggregated statistics for the authenticated provider. |

Example Response for paginated `/api/v1/dashboard/appointments/all/?page=1`:
```json
{
    "success": true,
    "message": "Success",
    "count": 42,
    "next": "http://.../?page=2",
    "previous": null,
    "page": 1,
    "page_size": 10,
    "data": [
        {
            "id": 1,
            "email": "client@example.com",
            "start_time": "2026-08-01T10:00:00Z",
            "status": "confirmed"
        }
    ]
}
```
