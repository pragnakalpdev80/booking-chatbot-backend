# config/exception_handler.py
"""
Custom DRF exception handler.
Returns structured JSON errors: {"error": "...", "code": "...", "details": {...}}
"""

import logging
from typing import Any

from googleapiclient.errors import HttpError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.calendar_app.models import GoogleCredential

logger = logging.getLogger(__name__)


def custom_exception_handler(exc: Exception, context: dict) -> Response | None:
    """
    Wrap DRF's default exception handler to return a consistent error shape.
    Conforms to CLAUDE.md §4.5 rules for GoogleCredential and HttpError exceptions.
    """
    if isinstance(exc, GoogleCredential.DoesNotExist):
        logger.warning("GoogleCredential.DoesNotExist caught: Google account not connected")
        return Response(
            {
                "error": "Google account not connected",
                "code": "google_not_connected",
                "status_code": 400,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, HttpError):
        logger.error("Google HttpError caught in exception handler: %s", exc)
        return Response(
            {
                "error": "Google Calendar service error.",
                "code": "bad_gateway",
                "status_code": 502,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    response = exception_handler(exc, context)

    if response is not None:
        error_data = {
            "error": _get_error_message(response.data),
            "code": _get_error_code(response),
            "status_code": response.status_code,
        }
        # Preserve field-level validation details if present
        if isinstance(response.data, dict) and len(response.data) > 1:
            error_data["details"] = response.data
        response.data = error_data

        view_name = context.get("view").__class__.__name__ if context.get("view") else "UnknownView"
        logger.warning(
            "DRF Exception handled in %s [%s %s]: %s",
            view_name,
            response.status_code,
            error_data["code"],
            error_data["error"],
        )
    else:
        # Unhandled exception — return 500
        logger.exception("Unhandled exception in view: %s", exc)
        response = Response(
            {
                "error": "An internal server error occurred.",
                "code": "server_error",
                "status_code": 500,
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response


def _get_error_message(data: Any) -> str:
    if isinstance(data, dict):
        # Pick first meaningful value
        for _key, val in data.items():
            if isinstance(val, list):
                return str(val[0])
            return str(val)
    if isinstance(data, list):
        return str(data[0])
    return str(data)


def _get_error_code(response: Response) -> str:
    code_map = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        429: "throttled",
        500: "server_error",
        502: "bad_gateway",
    }
    return code_map.get(response.status_code, "error")
