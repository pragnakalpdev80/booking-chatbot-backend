import datetime

from django.utils import timezone

from apps.calendar_app.models import Booking, BookingStatus


class DashboardSelector:
    @staticmethod
    def get_appointments(
        provider_id: int,
        start_date_str: str | None = None,
        end_date_str: str | None = None,
        email_str: str | None = None,
    ):
        """Get appointments for a provider, strictly filtered by CONFIRMED status."""
        qs = Booking.objects.filter(
            provider_id=provider_id,
            status=BookingStatus.CONFIRMED,
        ).order_by("start_time")

        if start_date_str:
            try:
                date_obj = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
                qs = qs.filter(start_time__date__gte=date_obj)
            except ValueError:
                pass

        if end_date_str:
            try:
                date_obj = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()
                qs = qs.filter(start_time__date__lte=date_obj)
            except ValueError:
                pass

        if email_str:
            qs = qs.filter(email__icontains=email_str)

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
