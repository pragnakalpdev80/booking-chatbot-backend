# accounts/urls.py
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import MeView, RegisterView

urlpatterns = [
    # User self-registration
    path("register/", RegisterView.as_view(), name="register"),
    # JWT login (returns access + refresh tokens)
    path("login/", TokenObtainPairView.as_view(), name="accounts_login"),
    # JWT token refresh
    path("token/refresh/", TokenRefreshView.as_view(), name="accounts_token_refresh"),
    # Retrieve own profile (requires JWT)
    path("me/", MeView.as_view(), name="accounts_me"),
]
