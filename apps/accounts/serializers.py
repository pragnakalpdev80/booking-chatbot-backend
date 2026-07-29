# apps/accounts/serializers.py
"""
Serializers for user registration, profile retrieval, and JWT token responses.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


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
            raise serializers.ValidationError({"password": "Passwords do not match."})  # nosec B105
        return attrs

    def create(self, validated_data):
        # Grant provider status so the user is recognized as a provider automatically
        validated_data["is_provider"] = True
        user = User.objects.create_user(**validated_data)
        return user


class MeSerializer(serializers.ModelSerializer):
    """Retrieve own profile."""

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "date_of_birth",
            "is_provider",
        ]
        read_only_fields = ["id", "username", "email", "is_provider"]
