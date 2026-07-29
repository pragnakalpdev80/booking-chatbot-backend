import logging

from rest_framework.views import APIView

from common.api.permissions import IsProviderUser
from common.api.response import ApiResponse

from .pagination import DashboardPagination
from .selectors import DashboardSelector
from .serializers import DashboardBookingSerializer

logger = logging.getLogger(__name__)


def _validate_start_date(start_date_str: str | None):
    if not start_date_str:
        return None
    import datetime

    from rest_framework import status

    try:
        parsed = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
        if parsed < datetime.date.today():
            return ApiResponse(
                {"error": "start_date cannot be in the past."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    except ValueError:
        return ApiResponse(
            {"error": "Invalid start_date format. Use YYYY-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


class DashboardAppointmentsView(APIView):
    """GET /api/v1/dashboard/appointments/"""

    permission_classes = [IsProviderUser]

    def get(self, request):
        provider_id = request.user.id
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")
        email_str = request.query_params.get("email")

        error_response = _validate_start_date(start_date_str)
        if error_response:
            return error_response

        appointments = DashboardSelector.get_appointments(
            provider_id, start_date_str, end_date_str, email_str
        )
        serializer = DashboardBookingSerializer(appointments, many=True)
        return ApiResponse(serializer.data)


class DashboardAllAppointmentsView(APIView):
    """GET /api/v1/dashboard/appointments/all/"""

    permission_classes = [IsProviderUser]

    def get(self, request):
        provider_id = request.user.id
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")
        email_str = request.query_params.get("email")

        error_response = _validate_start_date(start_date_str)
        if error_response:
            return error_response

        qs = DashboardSelector.get_all_appointments(
            provider_id, start_date_str, end_date_str, email_str
        )

        paginator = DashboardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = DashboardBookingSerializer(page, many=True)

        return ApiResponse.paginated_response(paginator, serializer.data, request)


class DashboardCancelledView(APIView):
    """GET /api/v1/dashboard/appointments/cancelled/"""

    permission_classes = [IsProviderUser]

    def get(self, request):
        provider_id = request.user.id
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")
        email_str = request.query_params.get("email")

        error_response = _validate_start_date(start_date_str)
        if error_response:
            return error_response

        qs = DashboardSelector.get_cancelled_appointments(
            provider_id, start_date_str, end_date_str, email_str
        )

        paginator = DashboardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = DashboardBookingSerializer(page, many=True)

        return ApiResponse.paginated_response(paginator, serializer.data, request)


class DashboardStatsView(APIView):
    """GET /api/v1/dashboard/stats/"""

    permission_classes = [IsProviderUser]

    def get(self, request):
        provider_id = request.user.id
        stats = DashboardSelector.get_stats(provider_id)
        return ApiResponse(stats)
