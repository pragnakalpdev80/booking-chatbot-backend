from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.calendar_app.models import BreakTime, Holiday, ProviderSettings


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_client(user):
    client = APIClient()
    user.is_staff = True
    user.save()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def regular_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestProviderSettingsView:
    def test_get_settings_success(self, admin_client, user):
        ProviderSettings.objects.create(user=user, timezone="Asia/Kolkata")
        url = reverse("admin_provider_settings")
        response = admin_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["data"]["timezone"] == "Asia/Kolkata"

    def test_patch_settings_success(self, admin_client, user):
        ProviderSettings.objects.create(user=user)
        url = reverse("admin_provider_settings")
        response = admin_client.patch(url, {"timezone": "America/New_York"}, format="json")
        assert response.status_code == status.HTTP_200_OK

        ps = ProviderSettings.objects.get(user=user)
        assert ps.timezone == "America/New_York"

    def test_patch_settings_invalid(self, admin_client, user):
        ProviderSettings.objects.create(user=user)
        url = reverse("admin_provider_settings")
        response = admin_client.patch(url, {"timezone": "InvalidZone"}, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_settings_unauthorized(self, regular_client):
        url = reverse("admin_provider_settings")
        response = regular_client.get(url)
        # Should be forbidden because IsAdminUser is required
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestProviderHolidaysView:
    def test_put_holidays_success(self, admin_client, user):
        ProviderSettings.objects.create(user=user)
        url = reverse("admin_provider_holidays")
        data = {"holidays": [{"date": "2026-12-25", "name": "Christmas"}]}
        response = admin_client.put(url, data, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert Holiday.objects.count() == 1

    def test_put_holidays_invalid(self, admin_client, user):
        ProviderSettings.objects.create(user=user)
        url = reverse("admin_provider_holidays")
        data = {"holidays": [{"date": "invalid-date", "name": "Christmas"}]}
        response = admin_client.put(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestProviderBreakTimesView:
    def test_put_break_times_success(self, admin_client, user):
        ProviderSettings.objects.create(user=user)
        url = reverse("admin_provider_breaks")
        data = {"breaks": [{"weekday": 0, "start": "12:00", "end": "13:00"}]}
        response = admin_client.put(url, data, format="json")
        assert response.status_code == status.HTTP_200_OK
        assert BreakTime.objects.count() == 1

    def test_put_break_times_overlap(self, admin_client, user):
        ProviderSettings.objects.create(user=user)
        url = reverse("admin_provider_breaks")
        data = {
            "breaks": [
                {"weekday": 0, "start": "12:00", "end": "14:00"},
                {"weekday": 0, "start": "13:00", "end": "15:00"},
            ]
        }
        response = admin_client.put(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "overlap" in response.data["data"]["error"]

    def test_put_break_times_invalid(self, admin_client, user):
        ProviderSettings.objects.create(user=user)
        url = reverse("admin_provider_breaks")
        data = {"breaks": [{"weekday": 0, "start": "invalid", "end": "13:00"}]}
        response = admin_client.put(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_break_times_outside_working_hours(self, admin_client, user):
        ps = ProviderSettings.objects.create(user=user)
        ps.day_schedules = {"0": {"is_active": True, "start": "09:00", "end": "17:00"}}
        ps.save()
        url = reverse("admin_provider_breaks")
        data = {"breaks": [{"weekday": 0, "start": "08:00", "end": "09:00"}]}
        response = admin_client.put(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_put_break_times_on_inactive_day(self, admin_client, user):
        ps = ProviderSettings.objects.create(user=user)
        ps.day_schedules = {"0": {"is_active": False, "start": "09:00", "end": "17:00"}}
        ps.save()
        url = reverse("admin_provider_breaks")
        data = {"breaks": [{"weekday": 0, "start": "12:00", "end": "13:00"}]}
        response = admin_client.put(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestGoogleOAuthViews:
    @patch("apps.calendar_app.views.logger.exception")
    @patch("apps.calendar_app.views._get_flow")
    def test_google_login(self, mock_get_flow, mock_logger_exc, admin_client):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = (
            "https://accounts.google.com/o/oauth2/auth",
            "state",
        )
        mock_flow.code_verifier = "mock_verifier"
        mock_get_flow.return_value = mock_flow

        url = reverse("calendar_google_login")
        response = admin_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert "accounts.google.com" in response.data["data"]["auth_url"]

    def test_google_callback_no_code(self, admin_client):
        url = reverse("calendar_oauth2callback")
        response = admin_client.get(url)
        assert response.status_code == status.HTTP_302_FOUND
        assert "oauth_failed" in response.url

    @patch("apps.calendar_app.views._get_flow")
    @patch("apps.calendar_app.views.cache")
    def test_google_callback_success(self, mock_cache, mock_get_flow, admin_client, user):
        mock_flow = MagicMock()
        mock_get_flow.return_value = mock_flow
        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "dummy"}'
        mock_creds.scopes = ["scope"]
        mock_flow.credentials = mock_creds

        def cache_get(key):
            if key == "oauth_verifier_test-state":
                return "verifier"
            if key == "oauth_user_test-state":
                return user.id
            return None

        mock_cache.get.side_effect = cache_get

        url = reverse("calendar_oauth2callback") + "?state=test-state&code=test-code"
        response = admin_client.get(url)

        assert response.status_code == status.HTTP_302_FOUND
        assert "success=google_connected" in response.url

    @patch("apps.calendar_app.views._get_flow")
    @patch("apps.calendar_app.views.cache")
    def test_google_callback_expired(self, mock_cache, mock_get_flow, admin_client):
        mock_flow = MagicMock()
        mock_get_flow.return_value = mock_flow

        def cache_get(key):
            if key == "oauth_verifier_test-state":
                return "verifier"
            if key == "oauth_user_test-state":
                return None
            return None

        mock_cache.get.side_effect = cache_get

        url = reverse("calendar_oauth2callback") + "?state=test-state&code=test-code"
        response = admin_client.get(url)

        assert response.status_code == status.HTTP_302_FOUND
        assert "error=expired" in response.url
