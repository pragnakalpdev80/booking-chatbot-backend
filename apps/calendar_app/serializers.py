# calendar_app/serializers.py
"""
Serializers for Google Calendar events, ProviderSettings, and anonymous Booking records.
"""

from rest_framework import serializers

from .models import Booking, BreakTime, Holiday, ProviderSettings


class BreakTimeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BreakTime
        fields = ["id", "weekday", "start", "end", "label"]
        read_only_fields = ["id"]

    def validate(self, data):
        if data["start"] >= data["end"]:
            raise serializers.ValidationError("Start time must be before end time.")

        day_schedules = self.context.get("day_schedules")
        if day_schedules:
            day_schedule = day_schedules.get(str(data["weekday"]))
            if not day_schedule or not day_schedule.get("is_active"):
                raise serializers.ValidationError("Cannot add break on an inactive day.")

            import datetime

            try:
                # Assuming format is "HH:MM" or "HH:MM:SS"
                work_start = datetime.time.fromisoformat(day_schedule["start"])
                work_end = datetime.time.fromisoformat(day_schedule["end"])
            except ValueError:
                raise serializers.ValidationError(
                    "Invalid working hours format in schedule."
                ) from None

            if data["start"] < work_start or data["end"] > work_end:
                raise serializers.ValidationError("Break must be within working hours.")

        return data


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "date", "label"]
        read_only_fields = ["id"]

    def validate_date(self, value):
        from django.utils import timezone

        if value < timezone.now().date():
            raise serializers.ValidationError("Holiday date cannot be in the past.")
        return value


class AvailableSlotSerializer(serializers.Serializer):
    """A single free time slot returned by the availability endpoint."""

    start = serializers.DateTimeField()
    end = serializers.DateTimeField()


class ProviderSettingsSerializer(serializers.ModelSerializer):
    break_times = BreakTimeSerializer(many=True, read_only=True)
    holidays = HolidaySerializer(many=True, read_only=True)
    is_google_connected = serializers.SerializerMethodField()

    def get_is_google_connected(self, obj):
        return hasattr(obj.user, "google_credential")

    def validate_timezone(self, value):
        import zoneinfo

        try:
            zoneinfo.ZoneInfo(value)
        except zoneinfo.ZoneInfoNotFoundError as err:
            raise serializers.ValidationError("Invalid timezone.") from err
        return value

    class Meta:
        model = ProviderSettings
        fields = [
            "id",
            "provider_name",
            "day_schedules",
            "slot_duration",
            "timezone",
            "updated_at",
            "break_times",
            "holidays",
            "is_google_connected",
        ]
        read_only_fields = ["id", "updated_at", "break_times", "holidays", "is_google_connected"]


class ProviderListSerializer(serializers.ModelSerializer):
    """Read-only representation of a provider for the frontend directory."""

    provider_name = serializers.CharField(source="provider_settings.provider_name", read_only=True)
    day_schedules = serializers.JSONField(source="provider_settings.day_schedules", read_only=True)
    timezone = serializers.CharField(source="provider_settings.timezone", read_only=True)

    class Meta:
        from django.contrib.auth.models import User

        model = User
        fields = [
            "id",
            "provider_name",
            "day_schedules",
            "timezone",
        ]


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
    provider_id = serializers.IntegerField()
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
