# calendar_app/tests/test_availability_cache.py
"""
Tests that _fetch_google_freebusy correctly uses the Redis/LocMem cache
and only calls the Google Calendar API when the cache is cold.

Follows CLAUDE.md §6 Testing Rules.
"""

from datetime import UTC
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache

from apps.calendar_app.models import GoogleCredential, ProviderSettings
from apps.calendar_app.selectors.availability import AvailabilitySelector


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure the cache is empty before each test."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def provider_setup(db, user):
    """Provider with settings and Google credential."""
    ps, _ = ProviderSettings.objects.get_or_create(
        user=user,
        defaults={
            "calendar_id": "primary",
            "timezone": "UTC",
        },
    )
    cred = GoogleCredential(user=user)
    cred.token = '{"token": "token", "refresh_token": "refresh", "client_id": "client", "client_secret": "secret", "token_uri": "uri"}'  # noqa: E501
    cred.save()
    return user, ps


@pytest.mark.django_db
class TestFreebusyCaching:
    @patch("apps.calendar_app.selectors.availability._build_service")
    @patch("apps.calendar_app.selectors.availability._get_admin_credential")
    def test_cache_miss_calls_google_api(self, mock_cred, mock_build, provider_setup):
        """On a cold cache, the Google freebusy API must be called once."""
        user, ps = provider_setup
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": []}}
        }

        from datetime import datetime

        start = datetime(2024, 8, 15, 9, 0, tzinfo=UTC)
        end = datetime(2024, 8, 15, 17, 0, tzinfo=UTC)

        selector = AvailabilitySelector(actor=user)
        result = selector._fetch_google_freebusy(ps, start, end)

        assert result == []
        mock_service.freebusy().query().execute.assert_called_once()

    @patch("apps.calendar_app.selectors.availability._build_service")
    @patch("apps.calendar_app.selectors.availability._get_admin_credential")
    def test_cache_hit_skips_google_api(self, mock_cred, mock_build, provider_setup):
        """On a warm cache, the Google freebusy API must NOT be called."""
        user, ps = provider_setup
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        from datetime import datetime

        start = datetime(2024, 8, 15, 9, 0, tzinfo=UTC)
        end = datetime(2024, 8, 15, 17, 0, tzinfo=UTC)

        # Pre-populate the cache manually
        cache_key = f"freebusy_{user.pk}_{ps.calendar_id}_{start.date().isoformat()}"
        cached_busy = [{"start": "2024-08-15T12:00:00Z", "end": "2024-08-15T14:00:00Z"}]
        cache.set(cache_key, cached_busy, 120)

        selector = AvailabilitySelector(actor=user)
        result = selector._fetch_google_freebusy(ps, start, end)

        assert result == cached_busy
        mock_service.freebusy().query().execute.assert_not_called()

    @patch("apps.calendar_app.selectors.availability._build_service")
    @patch("apps.calendar_app.selectors.availability._get_admin_credential")
    def test_first_call_populates_cache(self, mock_cred, mock_build, provider_setup):
        """After the first API call, the result must be stored in the cache."""
        user, ps = provider_setup
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        busy = [{"start": "2024-08-20T10:00:00Z", "end": "2024-08-20T10:30:00Z"}]
        mock_service.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": busy}}
        }

        from datetime import datetime

        start = datetime(2024, 8, 20, 9, 0, tzinfo=UTC)
        end = datetime(2024, 8, 20, 17, 0, tzinfo=UTC)

        selector = AvailabilitySelector(actor=user)
        selector._fetch_google_freebusy(ps, start, end)

        cache_key = f"freebusy_{user.pk}_{ps.calendar_id}_{start.date().isoformat()}"
        assert cache.get(cache_key) == busy
