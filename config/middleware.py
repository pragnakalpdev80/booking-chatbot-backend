# config/middleware.py
"""
Request logging middleware for Django.
Logs method, path, status code, duration_ms, and user info for every HTTP request.
"""

import logging
import time
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """
    Middleware that records structured timing and status information for incoming HTTP requests.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        start_time = time.perf_counter()

        response = self.get_response(request)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        status_code = response.status_code

        # Extract user identification safely
        user_str = "anon"
        if hasattr(request, "user") and request.user.is_authenticated:
            user_str = getattr(request.user, "username", str(request.user))

        # Extract session key if header or query param present
        session_key = request.headers.get("X-Session-Key") or request.GET.get("session_key", "")
        session_info = f" session={session_key}" if session_key else ""

        log_msg = (
            f"{request.method} {request.path} {status_code} "
            f"in {duration_ms}ms (user={user_str}){session_info}"
        )

        if status_code >= 500:
            logger.error(log_msg)
        elif status_code >= 400:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)

        return response
