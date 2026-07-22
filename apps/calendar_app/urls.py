# calendar_app/urls.py
from django.urls import path

from .views import (
    AvailabilityView,
    BookAppointmentView,
    BookingsByEmailView,
    CalendarEventDetailView,
    CalendarEventsView,
    CancelAppointmentView,
    GoogleLoginView,
    GoogleOAuth2CallbackView,
    ProviderSettingsView,
    RescheduleAppointmentView,
)

# Calendar / OAuth (admin-only)
calendar_patterns = [
    path("calendar/login/", GoogleLoginView.as_view(), name="calendar_google_login"),
    path("calendar/oauth2callback/", GoogleOAuth2CallbackView.as_view(), name="calendar_oauth2callback"),
    path("calendar/events/", CalendarEventsView.as_view(), name="calendar_events_list"),
    path("calendar/events/<str:event_id>/", CalendarEventDetailView.as_view(), name="calendar_event_detail"),
    path("calendar/availability/", AvailabilityView.as_view(), name="calendar_availability"),
]

# Anonymous appointment management
appointment_patterns = [
    path("appointments/book/", BookAppointmentView.as_view(), name="appointments_booking_create"),
    path("appointments/by-email/", BookingsByEmailView.as_view(), name="appointments_booking_list"),
    path("appointments/<str:event_id>/reschedule/", RescheduleAppointmentView.as_view(), name="appointments_booking_reschedule"),
    path("appointments/<str:event_id>/cancel/", CancelAppointmentView.as_view(), name="appointments_booking_cancel"),
]

# Admin settings
admin_patterns = [
    path("admin/provider-settings/", ProviderSettingsView.as_view(), name="admin_provider_settings"),
]

urlpatterns = calendar_patterns + appointment_patterns + admin_patterns