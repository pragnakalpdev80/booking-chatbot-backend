from django.db.models import QuerySet

from apps.calendar_app.models import Booking, BookingStatus
from common.selectors.base import BaseSelector


class BookingSelector(BaseSelector):
    @classmethod
    def get_bookings_by_email(cls, email: str) -> QuerySet[Booking]:
        return Booking.objects.filter(email=email).exclude(status=BookingStatus.CANCELLED)
