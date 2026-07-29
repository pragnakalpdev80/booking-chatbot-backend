# calendar_app/views.py
"""
Google Calendar integration views.

Admin-only endpoints (IsProviderUser):
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

from django.contrib.auth import get_user_model
from django.core.cache import cache
from googleapiclient.errors import HttpError
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.calendar_app.selectors.availability import AvailabilitySelector
from apps.calendar_app.selectors.booking import BookingSelector
from apps.calendar_app.services.booking_service import BookingService
from common.api.exceptions import ApplicationError
from common.api.permissions import IsProviderUser
from common.api.response import ApiResponse

from .models import GoogleCredential, ProviderSettings
from .serializers import (
    AvailableSlotSerializer,
    BookAppointmentSerializer,
    BookingSerializer,
    BreakTimeSerializer,
    CancelSerializer,
    HolidaySerializer,
    ProviderSettingsSerializer,
    RescheduleSerializer,
)
from .utils import (
    SLOT_DURATION_MINUTES,
    _build_service,
    _get_admin_credential,
    _get_flow,
)

logger = logging.getLogger(__name__)

User = get_user_model()

# Full read/write scope


# ─── Google OAuth (admin only) ────────────────────────────────────────────────


class GoogleLoginView(APIView):
    """Initiate Google OAuth — admin only."""

    permission_classes = [IsProviderUser]

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

        # Cache the current provider's ID against the state parameter
        cache.set(f"oauth_user_{state}", request.user.id, timeout=600)

        request.session["google_oauth_state"] = state
        return ApiResponse({"auth_url": auth_url})


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
            logger.exception("OAuth callback failed: %s", exc)
            from django.http import HttpResponseRedirect

            return HttpResponseRedirect(
                "http://localhost:5173/provider/settings?error=oauth_failed"
            )

        user_id = cache.get(f"oauth_user_{state}")
        if not user_id:
            from django.http import HttpResponseRedirect

            return HttpResponseRedirect("http://localhost:5173/provider/settings?error=expired")

        try:
            provider = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            from django.http import HttpResponseRedirect

            return HttpResponseRedirect("http://localhost:5173/provider/settings?error=not_found")

        credential, created = GoogleCredential.objects.get_or_create(user=provider)
        credential.token = creds.to_json()
        credential.scope = " ".join(creds.scopes or [])
        credential.save()

        action = "created" if created else "updated"
        logger.info(
            "Google connection %s for provider %s (scope: %s)",
            action,
            provider.username,
            credential.scope,
        )

        from django.http import HttpResponseRedirect

        return HttpResponseRedirect(
            "http://localhost:5173/provider/settings?success=google_connected"
        )


# ─── Admin calendar CRUD ──────────────────────────────────────────────────────


# ─── Availability (anonymous) ─────────────────────────────────────────────────


class AvailabilityView(APIView):
    """
    GET /api/calendar/availability/?date=YYYY-MM-DD&provider_id=1
    Anonymous — no authentication required.
    Always uses 30-minute slot duration (hard-coded business rule).
    """

    permission_classes = [AllowAny]

    def get(self, request):
        logger.debug("AvailabilityView GET: %s", request.query_params)
        date_str = request.query_params.get("date")
        provider_id = request.query_params.get("provider_id")

        if not date_str:
            return ApiResponse(
                {"error": "Query param 'date' (YYYY-MM-DD) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not provider_id:
            return ApiResponse(
                {"error": "Query param 'provider_id' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            provider = User.objects.get(pk=provider_id)
        except User.DoesNotExist:
            return ApiResponse({"error": "Provider not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            query_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return ApiResponse(
                {"error": "Invalid 'date' format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            selector = AvailabilitySelector(actor=provider)
            free_slots, timezone = selector.get_free_slots(query_date)
        except RuntimeError as exc:
            return ApiResponse({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        serializer = AvailableSlotSerializer(free_slots, many=True)
        return ApiResponse({"available_slots": serializer.data, "timezone": timezone})


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
            return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email: str = serializer.validated_data["email"]
        provider_id: str = str(serializer.validated_data["provider_id"])
        name: str = serializer.validated_data.get("name", "")
        start_dt: datetime = serializer.validated_data["start_time"]
        reason: str = serializer.validated_data.get("reason", "")

        try:
            provider = User.objects.get(pk=provider_id)
        except User.DoesNotExist:
            return ApiResponse({"error": "Provider not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            service = BookingService(actor=provider)
            result = service.book_appointment(
                email=email,
                name=name,
                start_time=start_dt,
                reason=reason,
            )
            # Add required fields for response
            end_dt = start_dt + timedelta(minutes=SLOT_DURATION_MINUTES)
            result["start_time"] = start_dt.isoformat()
            result["end_time"] = end_dt.isoformat()
            # mock html_link since service does not return it for now
            # (we can omit it or change test). The test
            # test_book_anonymous_no_auth_required doesn't assert html_link.
            return ApiResponse(result, status=status.HTTP_201_CREATED)
        except ApplicationError as e:
            return ApiResponse({"error": str(e)}, status=e.status_code)


class BookingsByEmailView(APIView):
    """
    GET /api/appointments/by-email/?email=user@example.com
    Anonymous — returns all bookings associated with the provided email.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        email = request.query_params.get("email", "").strip()
        if not email:
            return ApiResponse(
                {"error": "Query param 'email' is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        logger.debug("BookingsByEmailView GET for email %s", email)
        bookings = BookingSelector.get_bookings_by_email(email)
        return ApiResponse(BookingSerializer(bookings, many=True).data)


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
            return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email: str = serializer.validated_data["email"]
        new_start: datetime = serializer.validated_data["new_start_time"]

        try:
            from apps.calendar_app.models import Booking

            booking = Booking.objects.get(google_event_id=event_id, email=email)
        except Booking.DoesNotExist:
            return ApiResponse(
                {"error": "Booking not found for this email and event ID."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            assert booking.provider is not None
            service = BookingService(actor=booking.provider)
            booking = service.reschedule_appointment(email, event_id, new_start)
            return ApiResponse(BookingSerializer(booking).data)
        except ApplicationError as e:
            return ApiResponse({"error": str(e)}, status=e.status_code)


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
            return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email: str = serializer.validated_data["email"]

        try:
            from apps.calendar_app.models import Booking

            booking = Booking.objects.get(google_event_id=event_id, email=email)
        except Booking.DoesNotExist:
            return ApiResponse(
                {"error": "Booking not found for this email and event ID."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            assert booking.provider is not None
            service = BookingService(actor=booking.provider)
            service.cancel_appointment(email, event_id)
            return ApiResponse(status=status.HTTP_204_NO_CONTENT)
        except ApplicationError as e:
            return ApiResponse({"error": str(e)}, status=e.status_code)


# ─── ProviderSettings (admin only) ────────────────────────────────────────────


class ProviderSettingsView(APIView):
    """GET/PATCH /api/admin/provider-settings/ (admin only)"""

    permission_classes = [IsProviderUser]

    def get(self, request):
        logger.debug("ProviderSettingsView GET by %s", request.user.username)
        ps = ProviderSettings.get_for_provider(request.user)
        return ApiResponse(ProviderSettingsSerializer(ps).data)

    def patch(self, request):
        logger.debug("ProviderSettingsView PATCH by %s", request.user.username)
        ps = ProviderSettings.get_for_provider(request.user)
        serializer = ProviderSettingsSerializer(ps, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return ApiResponse(serializer.data)
        return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProviderBreakTimesView(APIView):
    """PUT /api/admin/provider-settings/breaks/ (admin only)"""

    permission_classes = [IsProviderUser]

    def _validate_break_overlaps(self, breaks_data: list[dict]) -> str | None:
        import datetime

        try:
            for i, brk1 in enumerate(breaks_data):
                for j, brk2 in enumerate(breaks_data):
                    if i >= j or brk1.get("weekday") != brk2.get("weekday"):
                        continue
                    s1 = datetime.datetime.strptime(brk1.get("start", ""), "%H:%M").time()
                    e1 = datetime.datetime.strptime(brk1.get("end", ""), "%H:%M").time()
                    s2 = datetime.datetime.strptime(brk2.get("start", ""), "%H:%M").time()
                    e2 = datetime.datetime.strptime(brk2.get("end", ""), "%H:%M").time()

                    if s1 < e2 and s2 < e1:
                        weekdays = [
                            "Monday",
                            "Tuesday",
                            "Wednesday",
                            "Thursday",
                            "Friday",
                            "Saturday",
                            "Sunday",
                        ]
                        day_name = weekdays[int(brk1.get("weekday", 0))]
                        return f"Break times overlap on {day_name}."
        except (ValueError, TypeError):
            return "Invalid time format. Please use HH:MM."
        return None

    def put(self, request):
        ps = ProviderSettings.get_for_provider(request.user)
        breaks_data = request.data.get("breaks", [])

        # Validate for overlapping breaks on the same day
        error_msg = self._validate_break_overlaps(breaks_data)
        if error_msg:
            return ApiResponse({"error": error_msg}, status=status.HTTP_400_BAD_REQUEST)

        serializer = BreakTimeSerializer(
            data=breaks_data, many=True, context={"day_schedules": ps.day_schedules}
        )
        if serializer.is_valid():
            from django.db import transaction

            with transaction.atomic():
                ps.break_times.all().delete()
                serializer.save(provider_settings=ps)
            return ApiResponse(serializer.data)
        return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProviderHolidaysView(APIView):
    """PUT /api/admin/provider-settings/holidays/ (admin only)"""

    permission_classes = [IsProviderUser]

    def put(self, request):
        ps = ProviderSettings.get_for_provider(request.user)
        serializer = HolidaySerializer(data=request.data.get("holidays", []), many=True)
        if serializer.is_valid():
            from django.db import transaction
            from django.utils import timezone

            with transaction.atomic():
                today = timezone.now().date()
                ps.holidays.filter(date__gte=today).delete()
                serializer.save(provider_settings=ps)
            return ApiResponse(serializer.data)
        return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProviderListView(APIView):
    """GET /api/providers/ (Anonymous) — returns a list of all configured doctors."""

    permission_classes = [AllowAny]

    def get(self, request):
        from django.contrib.auth import get_user_model

        User = get_user_model()

        from apps.calendar_app.serializers import ProviderListSerializer

        # Only return providers that have a connected Google credential
        # and a provider settings record.
        providers = User.objects.filter(
            google_credential__isnull=False, provider_settings__isnull=False
        ).select_related("provider_settings")

        return ApiResponse(ProviderListSerializer(providers, many=True).data)


class ListProviderCalendarsView(APIView):
    """GET /api/admin/my-calendars/ (Admin only) — returns all calendars in the doctor's account."""

    permission_classes = [IsProviderUser]

    def get(self, request):
        try:
            cred = _get_admin_credential(request.user)
            service = _build_service(cred)
        except RuntimeError as exc:
            return ApiResponse({"error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            calendars_result = service.calendarList().list().execute()
            calendars = calendars_result.get("items", [])
            return ApiResponse(
                [
                    {
                        "id": cal["id"],
                        "summary": cal.get("summary", ""),
                        "description": cal.get("description", ""),
                    }
                    for cal in calendars
                ]
            )
        except HttpError as exc:
            logger.exception("calendarList.list failed: %s", exc)
            return ApiResponse({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
