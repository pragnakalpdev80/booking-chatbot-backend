# chatbot/models.py
"""
Conversation session and message history for the anonymous Groq chatbot.

ConversationSession — one per anonymous chat thread (UUID session_key)
                      Stores the user_email once collected, plus lightweight
                      conversational state (intent, pending_slot).
Message             — each turn (user / assistant / tool) stored in DB
"""

import uuid

from django.db import models


class ConversationSession(models.Model):
    """
    An anonymous chat session.

    The `session_key` UUID is returned to the client on creation and must be
    passed with every subsequent request. No user account is required.
    """

    from django.contrib.auth.models import User

    provider = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="chat_sessions",
        help_text="The doctor this session is bound to.",
        null=True,  # Initially true to allow migration, but effectively required
    )

    session_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Client-side session identifier — returned on session creation.",
    )
    user_email = models.EmailField(
        blank=True,
        default="",
        db_index=True,
        help_text="Email collected mid-conversation; used as lookup key for CRUD ops.",
    )
    # Lightweight state machine fields — avoids Redis for single-server deployments
    intent = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Current detected intent: book|check|reschedule|cancel|none",
    )
    pending_slot = models.JSONField(
        null=True,
        blank=True,
        help_text='Temporarily holds {"start": "...", "end": "..."} awaiting email confirmation.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conversation Session"
        verbose_name_plural = "Conversation Sessions"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        email_display = self.user_email or "anonymous"
        return f"Session({self.session_key}, email={email_display})"


class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"
    SYSTEM = "system", "System"
    TOOL = "tool", "Tool"


class Message(models.Model):
    """A single message in a conversation session."""

    session = models.ForeignKey(
        ConversationSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=20, choices=MessageRole.choices)
    content = models.TextField()
    # Store tool call / tool result metadata as JSON when role == "tool"
    tool_call_id = models.CharField(max_length=255, blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        ordering = ["timestamp"]

    def __str__(self) -> str:
        return f"Message(role={self.role}, session={self.session.session_key})"
