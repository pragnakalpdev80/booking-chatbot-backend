# chatbot/admin.py
from django.contrib import admin

from .models import ConversationSession, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ["role", "content", "tool_call_id", "timestamp"]
    ordering = ["timestamp"]
    can_delete = False


@admin.register(ConversationSession)
class ConversationSessionAdmin(admin.ModelAdmin):
    list_display = [
        "session_key",
        "user_email",
        "intent",
        "created_at",
        "updated_at",
    ]
    search_fields = ["session_key", "user_email"]
    list_filter = ["intent"]
    readonly_fields = ["session_key", "created_at", "updated_at"]
    inlines = [MessageInline]


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["session", "role", "timestamp"]
    list_filter = ["role"]
    readonly_fields = ["session", "role", "content", "tool_call_id", "timestamp"]
