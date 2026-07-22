# Calendar App Overview

> **Namespace:** `apps.calendar_app`
> **Purpose:** Handles Google OAuth authorization, Calendar API abstraction, booking records, and provider settings.

---

## 1. Core Responsibilities

The `calendar_app` operates as the primary integration layer between the internal Django system and the external Google Calendar API. It enforces the architectural rule that **Google Calendar is the single source of truth** for all appointment times and details.

---

## 2. Models

### `ProviderSettings` (Singleton)
Stores the administrative configuration for the calendar (e.g., working hours, slot durations, timezone). Only one instance should exist in the database.

```python
class ProviderSettings(models.Model):
    provider_name = models.CharField(max_length=255, default="Default Provider")
    timezone = models.CharField(max_length=50, default="UTC")
    work_start = models.TimeField(default=time(9, 0))
    work_end = models.TimeField(default=time(17, 0))
    work_days = ArrayField(models.IntegerField(), default=list) # 0=Mon, 4=Fri
    slot_duration = models.IntegerField(default=30) # minutes
```

### `GoogleCredential`
Stores the encrypted OAuth tokens granted by the Admin.

```python
class GoogleCredential(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    token = fields.EncryptedTextField()  # Fernet encrypted
    token_updated_at = models.DateTimeField(auto_now=True)
    scope = models.TextField(blank=True)
```
- **Constraint:** Only **one** row is ever permitted in this table.
- **Usage:** Provides a `get_credentials()` method that deserializes the token into a `google.oauth2.credentials.Credentials` object for building the Google API service.

### `Booking`
An internal reference model linking a Django User to a Google Calendar event.

```python
class Booking(models.Model):
    STATUS_CHOICES = [('confirmed', 'Confirmed'), ('cancelled', 'Cancelled'), ('rescheduled', 'Rescheduled')]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")
    google_event_id = models.CharField(max_length=255, unique=True)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
```
- **Note:** The actual event title, description, and attendees live on Google Calendar. This model just tracks ownership so users can manage their own bookings.

---

## 3. Asynchronous Tasks (`tasks.py`)
All Google Calendar write operations are dispatched asynchronously via **Celery** to prevent blocking the chatbot response while waiting on Google's API latency.

| Task Name | Arguments | Action |
|-----------|-----------|--------|
| `insert_google_calendar_event` | `user_id, summary, start_time_iso, end_time_iso, description` | Calls `events().insert()` and creates a local `Booking` record. |
| `patch_google_calendar_event` | `user_id, event_id, new_start_iso, new_end_iso` | Calls `events().patch()` and updates the local `Booking` times. |
| `delete_google_calendar_event` | `user_id, event_id` | Calls `events().delete()` and sets `Booking.status = 'cancelled'`. |

---

## 4. Endpoints & Views

### Admin Routes (IsAdminUser)
| Endpoint | Method | Action |
|----------|--------|--------|
| `/api/calendar/login/` | `GET` | Initiates Google OAuth consent flow using `google_auth_oauthlib.flow.Flow`. |
| `/api/calendar/oauth2callback/` | `GET` | Exchanges code for tokens, encrypts them, and saves to `GoogleCredential`. |
| `/api/calendar/events/` | `GET` | Lists upcoming events from the admin's primary calendar. |
| `/api/admin/provider-settings/` | `PATCH` | Updates working hours. Payload: `{"work_start": "08:00:00"}` |

### User Routes (IsAuthenticated)

#### `GET /api/calendar/availability/`
Queries Google's `freebusy` API to find open times, filtering against `ProviderSettings`.
- **Query Params:** `?date=2026-07-25`
- **Response:**
  ```json
  {
      "timezone": "UTC",
      "available_slots": [
          {"start": "2026-07-25T09:00:00Z", "end": "2026-07-25T09:30:00Z"},
          {"start": "2026-07-25T10:00:00Z", "end": "2026-07-25T10:30:00Z"}
      ]
  }
  ```

#### `POST /api/appointments/book/`
Books a slot on the admin's calendar.
- **Payload:** `{"start_time": "...", "end_time": "...", "reason": "General Checkup"}`
- **Action:** Verifies slot is free, then calls `insert_google_calendar_event.delay()`.

#### `PATCH /api/appointments/<event_id>/reschedule/`
Moves an existing appointment.
- **Payload:** `{"new_start_time": "...", "new_end_time": "..."}`
- **Action:** Validates ownership via `Booking`, checks freebusy, calls `patch_google_calendar_event.delay()`.

#### `DELETE /api/appointments/<event_id>/cancel/`
Cancels an appointment.
- **Action:** Validates ownership, calls `delete_google_calendar_event.delay()`.
