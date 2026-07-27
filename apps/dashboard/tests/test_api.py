from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.calendar_app.models import Booking, BookingStatus


@pytest.mark.django_db
class TestDashboardEndpoints:
    @pytest.fixture
    def setup_data(self, user):
        now = timezone.now()
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        # Past (Yesterday)
        Booking.objects.create(
            provider=user,
            email="1@test.com",
            start_time=yesterday,
            end_time=yesterday + timedelta(minutes=30),
            reason="Checkup",
            status=BookingStatus.CONFIRMED,
            google_event_id="evt1",
        )
        # Future (Tomorrow)
        Booking.objects.create(
            provider=user,
            email="2@test.com",
            start_time=tomorrow,
            end_time=tomorrow + timedelta(minutes=30),
            status=BookingStatus.CONFIRMED,
            google_event_id="evt2",
        )
        # Cancelled
        Booking.objects.create(
            provider=user,
            email="3@test.com",
            start_time=tomorrow,
            end_time=tomorrow + timedelta(minutes=30),
            status=BookingStatus.CANCELLED,
            google_event_id="evt3",
        )

    def test_get_appointments(self, auth_client, user, setup_data):
        url = reverse("dashboard_appointments")
        response = auth_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        # Future confirmed AND cancelled should be returned (Tomorrow Confirmed and Tomorrow Cancelled)
        assert len(response.data["data"]) == 2
        emails = [item["email"] for item in response.data["data"]]
        assert "2@test.com" in emails
        assert "3@test.com" in emails

    def test_get_appointments_filtered(self, auth_client, user, setup_data):
        url = reverse("dashboard_appointments")
        tomorrow_str = (timezone.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        response = auth_client.get(f"{url}?start_date={tomorrow_str}&end_date={tomorrow_str}")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["data"]) == 2

    def test_get_appointments_past_date_rejected(self, auth_client, user, setup_data):
        url = reverse("dashboard_appointments")
        yesterday_str = (timezone.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        response = auth_client.get(f"{url}?start_date={yesterday_str}")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "cannot be in the past" in response.data["data"]["error"]

    def test_get_all_appointments(self, auth_client, user, setup_data):
        url = reverse("dashboard_all_appointments")
        response = auth_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 3
        assert "next" in response.data
        assert "previous" in response.data
        assert response.data["page"] == 1
        assert response.data["page_size"] == 10
        assert len(response.data["data"]) == 3
        # Should be ordered descending (latest first, i.e., tomorrow > yesterday)
        assert response.data["data"][0]["email"] in ["2@test.com", "3@test.com"]

    def test_get_cancelled_appointments(self, auth_client, user, setup_data):
        url = reverse("dashboard_cancelled_appointments")
        response = auth_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        assert response.data["data"][0]["email"] == "3@test.com"

    def test_get_stats(self, auth_client, user, setup_data):
        url = reverse("dashboard_stats")
        response = auth_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        data = response.data["data"]
        assert data["total"] == 3
        assert data["today"] == 0
        assert data["upcoming"] == 2
        assert data["cancelled"] == 1
