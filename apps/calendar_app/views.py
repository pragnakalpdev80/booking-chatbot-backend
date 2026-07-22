# calendar_app/views.py
"""
Google Calendar integration views.

Admin-only endpoints (IsAdminUser):
  GET    /api/calendar/login/                       — initiate Google OAuth
  GET    /api/calendar/oauth2callback/              — handle OAuth callback
  GET    /api/calendar/events/                      — list upcoming events
  GET    /api/calendar/events/<event_id>/           — retrieve single event
  PATCH  /api/calendar/events/<event_id>/           — update event
  DELETE /api/calendar/events/<event_id>/           — delete event
  GET    /api/admin/provider-settings/              — view provider settings
  PATCH  /api/admin/provider-settings/              — update provider settings

Anonymous endpoints (AllowAny):
  GET    /api/calendar/availability/                — list free slots
  POST   /api/appointments/book/                    — book a slot (email required in body)
  GET    /api/appointments/by-email/                — list bookings for an email
  PATCH  /api/appointments/<event_id>/reschedule/   — reschedule (email required in body)
  DELETE /api/appointments/<event_id>/cancel/       — cancel (email required in body)
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from django.contrib.auth.models import User
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google_auth_oauthlib.flow import Flow
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Booking, BookingStatus, GoogleCredential, ProviderSettings
from .serializers import (
    AvailableSlotSerializer,
    BookAppointmentSerializer,
    BookingSerializer,
    CancelSerializer,
    EventSerializer,
    ProviderSettingsSerializer,
    RescheduleSerializer,
)
from .tasks import (
    task_cancel_event,
    task_patch_event,
)

logger = logging.getLogger(__name__)

# Full read/write scope
SCOPES = ["https://www.googleapis.com/auth/calendar"]
SLOT_DURATION_MINUTES = 30  # Hard-coded business rule


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _get_flow(state=None) -> Flow:
    kwargs = {
        "scopes": SCOPES,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
    }
    if state:
        kwargs["state"] = state
    return Flow.from_client_secrets_file(
        settings.GOOGLE_CLIENT_SECRETS_FILE,
        **kwargs
    )


def _get_admin_credential() -> GoogleCredential:
    """Return the single admin/owner GoogleCredential or raise."""
    try:
        return GoogleCredential.objects.select_related("user").get()
    except GoogleCredential.DoesNotExist:
        raise RuntimeError(
            "Google Calendar is not connected. An admin must complete the OAuth flow first."
        )


def _build_service(credential: GoogleCredential):
    """Build and return an authenticated Google Calendar API service."""
    creds = credential.get_credentials()
    return build("calendar", "v3", credentials=creds)


def _check_freebusy(service, start_dt: datetime, end_dt: datetime) -> bool:
    """Return True if the slot is free (no conflicting events)."""
    body = {
        "timeMin": start_dt.isoformat(),
        "timeMax": end_dt.isoformat(),
        "items": [{"id": "primary"}],
    }
    try:
        result = service.freebusy().query(body=body).execute()
        busy_slots = result.get("calendars", {}).get("primary", {}).get("busy", [])
        return len(busy_slots) == 0
    except HttpError as exc:
        logger.error("freebusy check failed: %s", exc)
        raise RuntimeError(f"Could not check calendar availability: {exc}") from exc


# ─── Google OAuth (admin only) ────────────────────────────────────────────────

class GoogleLoginView(APIView):
    """Initiate Google OAuth — admin only."""

    permission_classes = [IsAdminUser]

    def get(self, request):
        logger.debug("GoogleLoginView GET by user %s", request.user.username)
        flow = _get_flow()
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        code_verifier = getattr(flow, "code_verifier", None)
        if code_verifier:
            cache.set(f"oauth_verifier_{state}", code_verifier, timeout=600)
        request.session["google_oauth_state"] = state
        return Response({"auth_url": auth_url})


class GoogleOAuth2CallbackView(APIView):
    """Handle Google OAuth callback — public so browser can hit it directly."""

    permission_classes = [AllowAny]

    def get(self, request):
        logger.debug("GoogleOAuth2CallbackView GET callback received")
        state = request.query_params.get("state")
        try:
            flow = _get_flow(state=state)
            code_verifier = cache.get(f"oauth_verifier_{state}")
            if code_verifier:
                flow.code_verifier = code_verifier
            flow.fetch_token(authorization_response=request.build_absolute_uri())
            creds = flow.credentials
        except Exception as exc:
            logger.error("OAuth callback failed: %s", exc)
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            return Response(
                {"error": "No superuser exists to attach the calendar to."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        credential, created = GoogleCredential.objects.get_or_create(user=admin_user)
        credential.set_token(creds.to_json())
        credential.scope = " ".join(creds.scopes or [])
        credential.save()

        action = "created" if created else "updated"
        logger.info(
            "GoogleCredential %s for admin %s (scope: %s)",
            action, admin_user.username, credential.scope,
        )
        return Response({"status": "connected", "scope": credential.scope})


# ─── Admin calendar CRUD ──────────────────────────────────────────────────────

class CalendarEventsView(APIView):
    """GET /api/calendar/events/ — list upcoming events (admin only)"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        logger.debug("CalendarEventsView GET by user %s", request.user.username)
        try:
            cred = _get_admin_credential()
            service = _build_service(cred)
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            result = service.events().list(
                calendarId="primary",
                maxResults=50,
                singleEvents=True,
                orderBy="startTime",
                timeMin=datetime.utcnow().isoformat() + "Z",
            ).execute()
        except HttpError as exc:
            logger.error("events.list failed: %s", exc)
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        events = result.get("items", [])
        return Response(EventSerializer(events, many=True).data)


class CalendarEventDetailView(APIView):
    """GET/PATCH/DELETE /api/calendar/events/<event_id>/ (admin only)"""

    permission_classes = [IsAdminUser]

    def get(self, request, event_id: str):
        logger.debug("CalendarEventDetailView GET by %s for %s", request.user.username, event_id)
        try:
            cred = _get_admin_credential()
            service = _build_service(cred)
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            event = service.events().get(calendarId="primary", eventId=event_id).execute()
        except HttpError as exc:
            code = exc.resp.status
            return Response(
                {"error": str(exc)},
                status=status.HTTP_404_NOT_FOUND if code == 404 else status.HTTP_502_BAD_GATEWAY,
            )
        return Response(EventSerializer(event).data)

    def patch(self, request, event_id: str):
        logger.debug("CalendarEventDetailView PATCH by %s for %s", request.user.username, event_id)
        try:
            _get_admin_credential()
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        task_patch_event.delay(event_id, request.data)
        logger.info("Admin queued patch for event %s", event_id)
        return Response({"status": "update queued", "event_id": event_id})

    def delete(self, request, event_id: str):
        logger.debug("CalendarEventDetailView DELETE by %s for %s", request.user.username, event_id)
        try:
            _get_admin_credential()
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        task_cancel_event.delay(event_id)
        logger.info("Admin queued delete for event %s", event_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── Availability (anonymous) ─────────────────────────────────────────────────

class AvailabilityView(APIView):
    """
    GET /api/calendar/availability/?date=YYYY-MM-DD
    Anonymous — no authentication required.
    Always uses 30-minute slot duration (hard-coded business rule).
    """

    permission_classes = [AllowAny]

    def get(self, request):
        logger.debug("AvailabilityView GET: %s", request.query_params)
        date_str = request.query_params.get("date")

        if not date_str:
            return Response(
                {"error": "Query param 'date' (YYYY-MM-DD) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            query_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"error": "Invalid 'date' format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ps = ProviderSettings.get_instance()
        tz = ZoneInfo(ps.timezone)

        if query_date.weekday() not in (ps.work_days or [0, 1, 2, 3, 4]):
            return Response({
                "available_slots": [],
                "message": "No bookings available on this day.",
                "timezone": ps.timezone,
            })

        start_of_day = datetime.combine(query_date, ps.work_start, tzinfo=tz)
        end_of_day = datetime.combine(query_date, ps.work_end, tzinfo=tz)
        slot_delta = timedelta(minutes=SLOT_DURATION_MINUTES)

        try:
            cred = _get_admin_credential()
            service = _build_service(cred)
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            freebusy_result = service.freebusy().query(
                body={
                    "timeMin": start_of_day.isoformat(),
                    "timeMax": end_of_day.isoformat(),
                    "items": [{"id": "primary"}],
                }
            ).execute()
        except HttpError as exc:
            logger.error("freebusy failed: %s", exc)
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        busy_intervals = freebusy_result.get("calendars", {}).get("primary", {}).get("busy", [])

        def _is_free(slot_start: datetime, slot_end: datetime) -> bool:
            for busy in busy_intervals:
                b_start = datetime.fromisoformat(busy["start"].replace("Z", "+00:00"))
                b_end = datetime.fromisoformat(busy["end"].replace("Z", "+00:00"))
                if slot_start < b_end and slot_end > b_start:
                    return False
            return True

        free_slots = []
        current = start_of_day
        while current + slot_delta <= end_of_day:
            slot_end = current + slot_delta
            if _is_free(current, slot_end):
                free_slots.append({"start": current, "end": slot_end})
            current = slot_end

        serializer = AvailableSlotSerializer(free_slots, many=True)
        return Response({"available_slots": serializer.data, "timezone": ps.timezone})


# ─── Anonymous booking endpoints ──────────────────────────────────────────────

class BookAppointmentView(APIView):
    """
    POST /api/appointments/book/
    Anonymous — email is required in the request body.
    end_time is always calculated server-side as start_time + 30 minutes.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        logger.debug("BookAppointmentView POST received")
        serializer = BookAppointmentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email: str = serializer.validated_data["email"]
        name: str = serializer.validated_data.get("name", "")
        start_dt: datetime = serializer.validated_data["start_time"]
        reason: str = serializer.validated_data.get("reason", "")

        # Enforce 30-minute duration — no client override allowed
        end_dt = start_dt + timedelta(minutes=SLOT_DURATION_MINUTES)

        # Enforce weekday-only bookings
        ps = ProviderSettings.get_instance()
        if start_dt.weekday() not in (ps.work_days or [0, 1, 2, 3, 4]):
            return Response(
                {"error": "Appointments are only available Monday to Friday."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            cred = _get_admin_credential()
            service = _build_service(cred)
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Mandatory freebusy guard
        try:
            if not _check_freebusy(service, start_dt, end_dt):
                return Response(
                    {"error": "The requested slot is not available. Please choose another time."},
                    status=status.HTTP_409_CONFLICT,
                )
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        event_body = {
            "summary": f"Appointment: {name or email}",
            "description": reason,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": ps.timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": ps.timezone},
            "attendees": [{"email": email}],
        }

        try:
            created_event = service.events().insert(
                calendarId="primary", body=event_body
            ).execute()
        except HttpError as exc:
            logger.error("events.insert failed: %s", exc)
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        google_event_id = created_event["id"]

        booking = Booking.objects.create(
            email=email,
            name=name,
            google_event_id=google_event_id,
            start_time=start_dt,
            end_time=end_dt,
            reason=reason,
            status=BookingStatus.CONFIRMED,
        )
        logger.info("Booking created: email=%s event=%s", email, google_event_id)

        return Response(
            {
                "booking_id": booking.pk,
                "google_event_id": google_event_id,
                "html_link": created_event.get("htmlLink"),
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "status": booking.status,
            },
            status=status.HTTP_201_CREATED,
        )


class BookingsByEmailView(APIView):
    """
    GET /api/appointments/by-email/?email=user@example.com
    Anonymous — returns all bookings associated with the provided email.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        email = request.query_params.get("email", "").strip()
        if not email:
            return Response(
                {"error": "Query param 'email' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        logger.debug("BookingsByEmailView GET for email %s", email)
        bookings = Booking.objects.filter(email=email).exclude(status=BookingStatus.CANCELLED)
        return Response(BookingSerializer(bookings, many=True).data)


class RescheduleAppointmentView(APIView):
    """
    PATCH /api/appointments/<event_id>/reschedule/
    Anonymous — email in body is used to verify ownership.
    new_end_time is always start + 30 minutes.
    """

    permission_classes = [AllowAny]

    def patch(self, request, event_id: str):
        logger.debug("RescheduleAppointmentView PATCH for event %s", event_id)
        serializer = RescheduleSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email: str = serializer.validated_data["email"]
        new_start: datetime = serializer.validated_data["new_start_time"]
        new_end = new_start + timedelta(minutes=SLOT_DURATION_MINUTES)

        # Ownership check via email
        try:
            booking = Booking.objects.get(google_event_id=event_id, email=email)
        except Booking.DoesNotExist:
            return Response(
                {"error": "Booking not found for this email and event ID."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Enforce weekday-only
        ps = ProviderSettings.get_instance()
        if new_start.weekday() not in (ps.work_days or [0, 1, 2, 3, 4]):
            return Response(
                {"error": "Appointments are only available Monday to Friday."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            cred = _get_admin_credential()
            service = _build_service(cred)
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # freebusy guard on new slot
        try:
            if not _check_freebusy(service, new_start, new_end):
                return Response(
                    {"error": "The requested new slot is not available."},
                    status=status.HTTP_409_CONFLICT,
                )
        except RuntimeError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        patch_body = {
            "start": {"dateTime": new_start.isoformat(), "timeZone": ps.timezone},
            "end": {"dateTime": new_end.isoformat(), "timeZone": ps.timezone},
        }

        task_patch_event.delay(event_id, patch_body)

        booking.start_time = new_start
        booking.end_time = new_end
        booking.status = BookingStatus.RESCHEDULED
        booking.save(update_fields=["start_time", "end_time", "status", "updated_at"])

        logger.info("Booking rescheduled: email=%s event=%s -> %s", email, event_id, new_start.isoformat())
        return Response(BookingSerializer(booking).data)


class CancelAppointmentView(APIView):
    """
    DELETE /api/appointments/<event_id>/cancel/
    Anonymous — email in body is used to verify ownership.
    """

    permission_classes = [AllowAny]

    def delete(self, request, event_id: str):
        logger.debug("CancelAppointmentView DELETE for event %s", event_id)
        serializer = CancelSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email: str = serializer.validated_data["email"]

        # Ownership check via email
        try:
            booking = Booking.objects.get(google_event_id=event_id, email=email)
        except Booking.DoesNotExist:
            return Response(
                {"error": "Booking not found for this email and event ID."},
                status=status.HTTP_404_NOT_FOUND,
            )

        task_cancel_event.delay(event_id)
        booking.status = BookingStatus.CANCELLED
        booking.save(update_fields=["status", "updated_at"])

        logger.info("Booking cancelled: email=%s event=%s", email, event_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── ProviderSettings (admin only) ────────────────────────────────────────────

class ProviderSettingsView(APIView):
    """GET/PATCH /api/admin/provider-settings/ (admin only)"""

    permission_classes = [IsAdminUser]

    def get(self, request):
        logger.debug("ProviderSettingsView GET by user %s", request.user.username)
        ps = ProviderSettings.get_instance()
        return Response(ProviderSettingsSerializer(ps).data)

    def patch(self, request):
        logger.debug("ProviderSettingsView PATCH by user %s", request.user.username)
        ps = ProviderSettings.get_instance()
        serializer = ProviderSettingsSerializer(ps, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info("ProviderSettings updated by %s", request.user.username)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)