import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def disable_throttling(settings):
    """Disable DRF throttling globally in tests to prevent 429 errors."""
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_CLASSES": [],
        "DEFAULT_THROTTLE_RATES": {},
    }


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="AdminPassword123!",  # nosec B106
    )


@pytest.fixture
def user(db):
    """Regular (non-admin) Django user — used only for testing admin route protection."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="TestPassword123!",  # nosec B106
        first_name="Test",
        last_name="User",
    )


@pytest.fixture
def auth_client(api_client, user):
    """Authenticated client with regular user JWT — for testing admin-only 403s."""
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture(autouse=True)
def celery_eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
