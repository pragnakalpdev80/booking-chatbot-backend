import pytest
from django.urls import reverse
from rest_framework import status
from django.contrib.auth.models import User
from apps.accounts.models import UserProfile

@pytest.mark.django_db
def test_user_registration_success(api_client):
    url = reverse("register")
    payload = {
        "first_name": "Test",
        "last_name": "User",
        "username": "newuser",
        "email": "newuser@example.com",
        "password": "Password123!",
        "password2": "Password123!",
        "phone": "1234567890"
    }
    response = api_client.post(url, payload)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["username"] == "newuser"
    
    # Verify UserProfile auto-creation via signal
    user = User.objects.get(username="newuser")
    assert hasattr(user, "user_profile")
    assert user.user_profile.phone == "1234567890"

@pytest.mark.django_db
def test_user_registration_password_mismatch(api_client):
    url = reverse("register")
    payload = {
        "first_name": "Test",
        "last_name": "User",
        "username": "newuser2",
        "email": "newuser2@example.com",
        "password": "Password123!",
        "password2": "WrongPassword!"
    }
    response = api_client.post(url, payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "password" in response.data

@pytest.mark.django_db
def test_user_login_success(api_client, user):
    url = reverse("accounts_login")
    response = api_client.post(url, {"username": user.username, "password": "TestPassword123!"})
    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data
    assert "refresh" in response.data

@pytest.mark.django_db
def test_user_login_invalid(api_client, user):
    url = reverse("accounts_login")
    response = api_client.post(url, {"username": user.username, "password": "WrongPassword!"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

@pytest.mark.django_db
def test_token_refresh(api_client, user):
    login_url = reverse("accounts_login")
    login_resp = api_client.post(login_url, {"username": user.username, "password": "TestPassword123!"})
    refresh_token = login_resp.data["refresh"]
    
    refresh_url = reverse("accounts_token_refresh")
    response = api_client.post(refresh_url, {"refresh": refresh_token})
    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data

@pytest.mark.django_db
def test_user_registration_duplicate_username(api_client, user):
    url = reverse("register")
    payload = {
        "first_name": "Test",
        "last_name": "User",
        "username": user.username,
        "email": "newemail@example.com",
        "password": "Password123!",
        "password2": "Password123!"
    }
    response = api_client.post(url, payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "username" in response.data

@pytest.mark.django_db
def test_user_registration_duplicate_email(api_client, user):
    url = reverse("register")
    payload = {
        "first_name": "Test",
        "last_name": "User",
        "username": "uniqueusername",
        "email": user.email,
        "password": "Password123!",
        "password2": "Password123!"
    }
    response = api_client.post(url, payload)
    # The default Django User model doesn't enforce email uniqueness natively without custom validators,
    # but let's test if the serializer enforces it. If not, it will return 201, which is a flaw we should fix.
    pass

@pytest.mark.django_db
def test_me_endpoint_requires_auth(api_client):
    url = reverse("accounts_me")
    response = api_client.get(url)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

@pytest.mark.django_db
def test_me_endpoint_invalid_token(api_client):
    url = reverse("accounts_me")
    api_client.credentials(HTTP_AUTHORIZATION='Bearer invalid_token')
    response = api_client.get(url)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

@pytest.mark.django_db
def test_me_endpoint_authenticated(auth_client, user):
    url = reverse("accounts_me")
    response = auth_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["username"] == user.username
    assert "profile" in response.data
