import logging

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from common.api.response import ApiResponse

from .selectors import DashboardSelector
from .serializers import DashboardBookingSerializer

logger = logging.getLogger(__name__)


class DashboardAppointmentsView(APIView):
    """GET /api/v1/dashboard/appointments/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        provider_id = request.user.id
        date_str = request.query_params.get("date")

        appointments = DashboardSelector.get_appointments(provider_id, date_str)
        serializer = DashboardBookingSerializer(appointments, many=True)
        return ApiResponse(serializer.data)


class DashboardStatsView(APIView):
    """GET /api/v1/dashboard/stats/"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        provider_id = request.user.id
        stats = DashboardSelector.get_stats(provider_id)
        return ApiResponse(stats)
