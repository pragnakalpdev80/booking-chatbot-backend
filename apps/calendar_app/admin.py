# calendar_app/admin.py
from django.contrib import admin

from .models import Booking, GoogleCredential, ProviderSettings


@admin.register(GoogleCredential)
class GoogleCredentialAdmin(admin.ModelAdmin):
    list_display = ["user", "token_updated_at", "scope"]
    readonly_fields = ["user", "token_updated_at", "scope"]


@admin.register(ProviderSettings)
class ProviderSettingsAdmin(admin.ModelAdmin):
    list_display = [
        "provider_name",
        "timezone",
        "work_start",
        "work_end",
        "slot_duration",
        "updated_at",
    ]
    readonly_fields = ["updated_at"]


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
