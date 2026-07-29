import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


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
    user = User.objects.create_superuser(
        username="admin",
        email="admin@example.com",
        password="AdminPassword123!",  # nosec B106
    )
    user.is_provider = True
    user.save()
    return user


@pytest.fixture
def user(db):
    """Regular provider user."""
    u = User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="TestPassword123!",  # nosec B106
        first_name="Test",
        last_name="User",
    )
    u.is_provider = True
    u.save()
    return u


@pytest.fixture
def auth_client(api_client, user):
    """Authenticated client with provider user JWT."""
    api_client.force_authenticate(user=user)
    return api_client


@pytest.fixture
def patient_user(db):
    """Regular (non-provider) Django user."""
    return User.objects.create_user(
        username="patientuser",
        email="patient@example.com",
        password="TestPassword123!",  # nosec B106
        first_name="Patient",
        last_name="User",
    )


@pytest.fixture
def patient_client(api_client, patient_user):
    """Authenticated client with non-provider user JWT."""
    api_client.force_authenticate(user=patient_user)
    return api_client


@pytest.fixture
def admin_client(api_client, admin_user):
    api_client.force_authenticate(user=admin_user)
    return api_client


@pytest.fixture(autouse=True)
def celery_eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
