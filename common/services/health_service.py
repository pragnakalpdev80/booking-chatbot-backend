"""Dependency probes backing the readiness endpoint.

Liveness ("is the process up?") needs no probing — it is answered by the view
returning at all. Readiness ("can the process actually serve traffic?") requires
checking the backing services the app cannot function without: the database and
the cache/broker (Redis). Each probe is isolated so one failing dependency is
reported individually rather than collapsing into a single opaque error.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import Error as DatabaseError
from django.db import connections

logger = logging.getLogger(__name__)


class HealthService:
    """Probes the dependencies required for the app to serve requests."""

    @classmethod
    def check_readiness(cls) -> dict[str, bool]:
        """Return each probed dependency mapped to whether it is reachable."""
        return {
            "database": cls._check_database(),
            "cache": cls._check_cache(),
        }

    @staticmethod
    def _check_database() -> bool:
        """True if the default database answers a trivial query."""
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError:
            logger.exception("Readiness probe: database unreachable")
            return False
        return True

    @staticmethod
    def _check_cache() -> bool:
        """True if the cache/broker accepts a write and reads it back."""
        try:
            cache.set("health_probe", "1", timeout=5)
            return cache.get("health_probe") == "1"
        except Exception:
            logger.exception("Readiness probe: cache unreachable")
            return False
