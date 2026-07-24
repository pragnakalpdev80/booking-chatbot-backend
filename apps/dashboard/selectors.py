import datetime

from django.utils import timezone

from apps.calendar_app.models import Booking, BookingStatus


class DashboardSelector:
    @staticmethod
    def get_appointments(provider_id: int, date_str: str | None = None):
        """Get appointments for a provider, optionally filtered by date (YYYY-MM-DD)."""
        qs = Booking.objects.filter(provider_id=provider_id).order_by("start_time")

        if date_str:
            try:
                date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                qs = qs.filter(start_time__date=date_obj)
            except ValueError:
                pass

        return qs

    @staticmethod
    def get_stats(provider_id: int):
        """Get stats for a provider."""
        today = timezone.now().date()
        qs = Booking.objects.filter(provider_id=provider_id)

        total_appointments = qs.count()
        today_appointments = qs.filter(start_time__date=today).count()
        upcoming_appointments = qs.filter(start_time__date__gt=today).count()
        cancelled_appointments = qs.filter(status=BookingStatus.CANCELLED).count()

        return {
            "total": total_appointments,
            "today": today_appointments,
            "upcoming": upcoming_appointments,
            "cancelled": cancelled_appointments,
        }
