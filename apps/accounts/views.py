# apps/accounts/views.py
"""
User auth endpoints:
  POST /api/accounts/register/          — self-registration
  POST /api/accounts/login/             — obtain JWT (delegated to simplejwt)
  POST /api/accounts/token/refresh/     — refresh JWT (delegated to simplejwt)
  GET  /api/accounts/me/                — retrieve own profile
"""

import logging

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import MeSerializer, RegisterSerializer

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
            return Response(
                {
                    "message": "Registration successful.",
                    "user_id": user.pk,
                    "username": user.username,
                },
                status=status.HTTP_201_CREATED,
            )
        logger.warning("User registration failed: %s", serializer.errors)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MeView(APIView):
    """Return the authenticated user's own profile."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        logger.debug("MeView GET for user %s", request.user.username)
        serializer = MeSerializer(request.user)
        return Response(serializer.data)
