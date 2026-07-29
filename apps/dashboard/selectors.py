import datetime
from typing import Any

from django.utils import timezone

from apps.calendar_app.models import Booking, BookingStatus


class DashboardSelector:
    @staticmethod
    def get_appointments(
        provider_id: Any,
        start_date_str: str | None = None,
        end_date_str: str | None = None,
        email_str: str | None = None,
    ):
        """Get upcoming appointments for a provider (CONFIRMED and strictly future)."""
        qs = Booking.objects.filter(
            provider_id=provider_id,
            status__in=[BookingStatus.CONFIRMED, BookingStatus.CANCELLED],
            start_time__gt=timezone.now(),
        ).order_by("start_time")

        return DashboardSelector._apply_filters(qs, start_date_str, end_date_str, email_str)

    @staticmethod
    def _apply_filters(
        qs, start_date_str: str | None, end_date_str: str | None, email_str: str | None
    ):
        """Helper to apply common date range and email filters to a queryset."""
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
    def get_all_appointments(
        provider_id: Any,
        start_date_str: str | None = None,
        end_date_str: str | None = None,
        email_str: str | None = None,
    ):
        """Get all appointments for a provider (CONFIRMED/CANCELLED), ordered by latest first."""
        qs = Booking.objects.filter(
            provider_id=provider_id,
            status__in=[BookingStatus.CONFIRMED, BookingStatus.CANCELLED],
        ).order_by("-start_time")
        return DashboardSelector._apply_filters(qs, start_date_str, end_date_str, email_str)

    @staticmethod
    def get_cancelled_appointments(
        provider_id: Any,
        start_date_str: str | None = None,
        end_date_str: str | None = None,
        email_str: str | None = None,
    ):
        """Get cancelled appointments for a provider, ordered by latest first."""
        qs = Booking.objects.filter(
            provider_id=provider_id, status=BookingStatus.CANCELLED
        ).order_by("-start_time")
        return DashboardSelector._apply_filters(qs, start_date_str, end_date_str, email_str)

    @staticmethod
    def get_stats(provider_id: Any):
        """Get stats for a provider."""
        today = timezone.now().date()
        now = timezone.now()
        qs = Booking.objects.filter(
            provider_id=provider_id, status__in=[BookingStatus.CONFIRMED, BookingStatus.CANCELLED]
        )

        total_appointments = qs.count()
        today_appointments = qs.filter(start_time__date=today).count()
        upcoming_appointments = qs.filter(start_time__gt=now).count()
        cancelled_appointments = qs.filter(status=BookingStatus.CANCELLED).count()

        return {
            "total": total_appointments,
            "today": today_appointments,
            "upcoming": upcoming_appointments,
            "cancelled": cancelled_appointments,
        }
