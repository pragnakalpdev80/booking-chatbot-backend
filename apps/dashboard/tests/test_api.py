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
        today = timezone.now()
        tomorrow = today + timedelta(days=1)

        # Today
        Booking.objects.create(
            provider=user,
            email="1@test.com",
            start_time=today,
            end_time=today + timedelta(minutes=30),
            status=BookingStatus.CONFIRMED,
            google_event_id="evt1",
        )
        # Tomorrow
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
        assert len(response.data["data"]) == 3

    def test_get_appointments_filtered(self, auth_client, user, setup_data):
        url = reverse("dashboard_appointments")
        today_str = timezone.now().strftime("%Y-%m-%d")
        response = auth_client.get(f"{url}?date={today_str}")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["data"]) == 1

    def test_get_stats(self, auth_client, user, setup_data):
        url = reverse("dashboard_stats")
        response = auth_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        data = response.data["data"]
        assert data["total"] == 3
        assert data["today"] == 1
        assert data["upcoming"] == 2
        assert data["cancelled"] == 1
