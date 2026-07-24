"""
Root URL configuration.

All API endpoints are under /api/:
  /api/accounts/     — user auth (register, login, JWT refresh, me)
  /api/calendar/     — Google Calendar OAuth + CRUD + availability
  /api/appointments/ — user booking (book, list, reschedule, cancel)
  /api/admin/        — admin-only endpoints (provider settings)
  /api/chat/         — Groq chatbot (sessions, messages)
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # User auth
    path("api/v1/accounts/", include("apps.accounts.urls")),
    # Google Calendar + appointments
    path("api/v1/", include("apps.calendar_app.urls")),
    # Groq chatbot
    path("api/v1/chat/", include("apps.chatbot.urls")),
    # Dashboard
    path("api/v1/dashboard/", include("apps.dashboard.urls")),
]
