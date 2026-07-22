# chatbot/urls.py
from django.urls import path

from .views import (
    DeleteSessionView,
    SendMessageView,
    SessionHistoryView,
    StartSessionView,
)

urlpatterns = [
    # Start a new anonymous conversation session
    path("sessions/", StartSessionView.as_view(), name="chat_start_session"),
    # Send a message and receive an AI response
    path("message/", SendMessageView.as_view(), name="chat_send_message"),
    # Retrieve full message history for a session
    path(
        "sessions/<uuid:session_key>/messages/",
        SessionHistoryView.as_view(),
        name="chat_session_history",
    ),
    # Delete / end a session
    path(
        "sessions/<uuid:session_key>/",
        DeleteSessionView.as_view(),
        name="chat_delete_session",
    ),
]
