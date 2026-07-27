# calendar_app/admin.py
from django.contrib import admin

from .models import Booking, BreakTime, GoogleCredential, Holiday, ProviderSettings, SlotLock


@admin.register(GoogleCredential)
class GoogleCredentialAdmin(admin.ModelAdmin):
    list_display = ["user", "token_updated_at", "scope"]
    readonly_fields = ["user", "token_updated_at", "scope"]


@admin.register(ProviderSettings)
class ProviderSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "provider_name",
        "timezone",
        "slot_duration",
        "updated_at",
    ]
    readonly_fields = ["updated_at"]


@admin.register(BreakTime)
class BreakTimeAdmin(admin.ModelAdmin):
    list_display = ["provider_settings", "weekday", "start", "end", "label"]
    list_filter = ["weekday"]


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ["provider_settings", "date", "label"]
    list_filter = ["date"]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = [
        "email",
        "name",
        "google_event_id",
        "start_time",
        "end_time",
        "status",
        "created_at",
    ]
    list_filter = ["status"]
    search_fields = ["email", "name", "google_event_id", "reason"]
    readonly_fields = ["google_event_id", "created_at", "updated_at"]
    ordering = ["-start_time"]


@admin.register(SlotLock)
class SlotLockAdmin(admin.ModelAdmin):
    list_display = [
        "slot_start",
        "slot_end",
        "session_key",
        "expires_at",
        "locked_at",
        "is_confirmed",
    ]
    list_filter = ["is_confirmed"]
    search_fields = ["session_key"]
    readonly_fields = ["locked_at"]
    ordering = ["-locked_at"]
