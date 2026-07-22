# apps/accounts/serializers.py
"""
Serializers for user registration, profile retrieval, and JWT token responses.
"""
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ["phone", "date_of_birth"]


class RegisterSerializer(serializers.ModelSerializer):
    """User self-registration serializer."""

    password = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
        validators=[validate_password],
    )
    password2 = serializers.CharField(
        write_only=True,
        required=True,
        style={"input_type": "password"},
        label="Confirm password",
    )
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    date_of_birth = serializers.DateField(required=False, allow_null=True, default=None)

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "username",
            "email",
            "password",
            "password2",
            "phone",
            "date_of_birth",
        ]
        extra_kwargs = {
            "first_name": {"required": True},
            "last_name": {"required": True},
            "email": {"required": True},
        }

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password2"):
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        phone = validated_data.pop("phone", "")
        date_of_birth = validated_data.pop("date_of_birth", None)

        user = User.objects.create_user(**validated_data)

        # UserProfile is auto-created by signal; update extra fields if provided
        profile = user.user_profile
        profile.phone = phone
        profile.date_of_birth = date_of_birth
        profile.save()

        return user


class MeSerializer(serializers.ModelSerializer):
    """Retrieve own profile."""

    profile = UserProfileSerializer(source="user_profile", read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "profile"]
        read_only_fields = fields
