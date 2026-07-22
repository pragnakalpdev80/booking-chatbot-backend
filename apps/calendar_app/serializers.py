# calendar_app/serializers.py
"""
Serializers for Google Calendar events, ProviderSettings, and anonymous Booking records.
"""
from datetime import timedelta

from rest_framework import serializers

from .models import Booking, ProviderSettings


class EventSerializer(serializers.Serializer):
    """Read-only representation of a Google Calendar event dict."""

    id = serializers.CharField(read_only=True)
    summary = serializers.CharField(read_only=True)
    start = serializers.DictField(read_only=True)
    end = serializers.DictField(read_only=True)
    htmlLink = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, required=False, allow_null=True)


class AvailableSlotSerializer(serializers.Serializer):
    """A single free time slot returned by the availability endpoint."""

    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class ProviderSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderSettings
        fields = [
            "id",
            "provider_name",
            "work_days",
            "work_start",
            "work_end",
            "slot_duration",
            "timezone",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class BookingSerializer(serializers.ModelSerializer):
    """Read serializer for Booking — used for listing and responses."""

    class Meta:
        model = Booking
        fields = [
            "id",
            "email",
            "name",
            "google_event_id",
            "start_time",
            "end_time",
            "reason",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "google_event_id", "status", "created_at"]


class BookAppointmentSerializer(serializers.Serializer):
    """
    Input for POST /api/appointments/book/

    end_time is NEVER accepted from the client — it is always derived
    as start_time + 30 minutes server-side to enforce the fixed slot rule.
    """

    email = serializers.EmailField()
    name = serializers.CharField(required=False, allow_blank=True, default="")
    start_time = serializers.DateTimeField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_start_time(self, value):
        """Reject bookings in the past."""
        from django.utils import timezone
        if value < timezone.now():
            raise serializers.ValidationError("Cannot book a slot in the past.")
        return value


class RescheduleSerializer(serializers.Serializer):
    """Input for PATCH /api/appointments/<event_id>/reschedule/"""

    email = serializers.EmailField()
    new_start_time = serializers.DateTimeField()

    def validate_new_start_time(self, value):
        from django.utils import timezone
        if value < timezone.now():
            raise serializers.ValidationError("Cannot reschedule to a slot in the past.")
        return value


class CancelSerializer(serializers.Serializer):
    """Input for DELETE /api/appointments/<event_id>/cancel/"""

    email = serializers.EmailField()