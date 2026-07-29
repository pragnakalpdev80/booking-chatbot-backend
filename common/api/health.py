"""Liveness and readiness endpoints.

Two distinct checks, deliberately separated (mirrors the standard Kubernetes
liveness/readiness split):

* **Liveness** (``/health/``) — answers "is the process up and serving?". It does
  no dependency I/O and always returns 200 if the worker can respond at all, so a
  transient database/cache outage never causes the orchestrator to *kill and
  restart* an otherwise-healthy process.
* **Readiness** (``/health/ready/``) — answers "can this process actually handle a
  request?". It probes the backing dependencies (database, cache/broker) and returns
  503 if any is down, so a not-yet-ready or degraded instance is pulled out of the
  load-balancer rotation without being restarted.

Both are public (no auth) — a probe runs before any credential is available, and
the readiness payload exposes only component up/down booleans, no internals.
"""

from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from common.services.health_service import HealthService


class LivenessView(APIView):
    """Process-up check — no dependency I/O, always 200 when reachable."""

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class ReadinessView(APIView):
    """Dependency check — 200 when every probed dependency is reachable, else 503."""

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        components = HealthService.check_readiness()
        all_ready = all(components.values())
        return Response(
            {
                "status": "ok" if all_ready else "error",
                "message": "Service healthy" if all_ready else "Service unavailable",
                "components": {
                    component: "ok" if ok else "error" for component, ok in components.items()
                },
            },
            status=status.HTTP_200_OK if all_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
