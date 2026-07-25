# apps/accounts/views.py
"""
User auth endpoints:
  POST /api/accounts/register/          — self-registration
  POST /api/accounts/login/             — obtain JWT (delegated to simplejwt)
  POST /api/accounts/token/refresh/     — refresh JWT (delegated to simplejwt)
  GET  /api/accounts/me/                — retrieve own profile
"""

import logging

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.api.response import ApiResponse

from .serializers import MeSerializer, RegisterSerializer

User = get_user_model()
logger = logging.getLogger(__name__)


class RegisterView(APIView):
    """Public endpoint — allows any unauthenticated request."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def post(self, request):
        logger.debug("RegisterView POST received data: %s", request.data.keys())
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            logger.info("New user registered: %s (id=%s)", user.username, user.pk)
            return ApiResponse(
                {
                    "message": "Registration successful.",
                    "user_id": user.pk,
                    "username": user.username,
                },
                status=status.HTTP_201_CREATED,
            )
        logger.warning("User registration failed: %s", serializer.errors)
        return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MeView(APIView):
    """Return the authenticated user's own profile."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        logger.debug("MeView GET for user %s", request.user.username)
        serializer = MeSerializer(request.user)
        return ApiResponse(serializer.data)

    def patch(self, request):
        logger.debug("MeView PATCH for user %s", request.user.username)
        serializer = MeSerializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return ApiResponse(serializer.data)
        return ApiResponse(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProviderListView(APIView):
    """GET /api/v1/accounts/providers/ — public list of providers."""

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        providers = User.objects.filter(is_staff=True).select_related("user_profile").order_by("id")
        data = [
            {
                "id": u.id,
                "name": u.get_full_name() or u.username,
                "specialty": getattr(getattr(u, "user_profile", None), "specialty", ""),
            }
            for u in providers
        ]
        return ApiResponse(data)
