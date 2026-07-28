import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status

User = get_user_model()


@pytest.mark.django_db
class TestRegisterView:
    def test_register_success(self, client):
        url = reverse("register")
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "username": "johndoe",
            "email": "john@example.com",
            "password": "StrongPassword123!",
            "password2": "StrongPassword123!",
            "phone": "1234567890",
            "date_of_birth": "1990-01-01",
        }
        response = client.post(url, data, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert "user_id" in response.data["data"]

        user = User.objects.get(username="johndoe")
        assert user.is_staff is True
        assert user.user_profile.phone == "1234567890"

    def test_register_password_mismatch(self, client):
        url = reverse("register")
        data = {
            "first_name": "John",
            "last_name": "Doe",
            "username": "johndoe",
            "email": "john@example.com",
            "password": "StrongPassword123!",
            "password2": "DifferentPassword123!",
        }
        response = client.post(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "password" in response.data["data"]


@pytest.mark.django_db
class TestMeView:
    def test_get_me_success(self, admin_client, admin_user):
        url = reverse("accounts_me")
        response = admin_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["username"] == admin_user.username

    def test_patch_me_success(self, admin_client, admin_user):
        url = reverse("accounts_me")
        data = {"first_name": "Updated", "profile": {"phone": "9876543210"}}
        response = admin_client.patch(url, data, format="json")
        assert response.status_code == status.HTTP_200_OK

        admin_user.refresh_from_db()
        assert admin_user.first_name == "Updated"
        assert admin_user.user_profile.phone == "9876543210"

    def test_patch_me_invalid(self, admin_client, admin_user):
        url = reverse("accounts_me")
        data = {"profile": {"date_of_birth": "invalid-date"}}
        response = admin_client.patch(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
