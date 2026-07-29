import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
class TestProviderListView:
    def test_provider_list_returns_staff_users(self, api_client):
        # Create a staff user with a profile
        staff_user = User.objects.create_user(
            username="dr_smith",
            password="pw",
            is_provider=True,
            first_name="John",
            last_name="Smith",
        )

        # Create a non-staff user (should not be in list)
        User.objects.create_user(username="patient", password="pw", is_provider=False)

        response = api_client.get("/api/v1/accounts/providers/")
        assert response.status_code == 200

        data = response.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == str(staff_user.id)
        assert data[0]["name"] == "John Smith"
        assert data[0]["specialty"] == ""

    def test_provider_list_empty_when_no_staff(self, api_client):
        response = api_client.get("/api/v1/accounts/providers/")
        assert response.status_code == 200
        assert response.json()["data"] == []

    def test_provider_list_no_auth_required(self, api_client):
        User.objects.create_user(username="staff1", password="pw", is_provider=True)
        # Client is not authenticated
        response = api_client.get("/api/v1/accounts/providers/")
        assert response.status_code == 200
        assert len(response.json()["data"]) == 1
