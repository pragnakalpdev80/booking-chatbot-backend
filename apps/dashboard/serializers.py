from rest_framework import serializers

from apps.calendar_app.models import Booking


class DashboardBookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = [
            "id",
            "email",
            "start_time",
            "end_time",
            "status",
            "google_event_id",
            "created_at",
            "updated_at",
        ]
