# apps/accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ["username", "email", "first_name", "last_name", "is_provider", "is_staff"]
    list_filter = ["is_provider", "is_staff", "is_superuser", "is_active"]
    fieldsets = list(UserAdmin.fieldsets or []) + [
        ("Custom Fields", {"fields": ("phone", "date_of_birth", "is_provider")}),
    ]
