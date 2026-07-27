from django.urls import path

from .views import (
    DashboardAllAppointmentsView,
    DashboardAppointmentsView,
    DashboardCancelledView,
    DashboardStatsView,
)

urlpatterns = [
    path("appointments/", DashboardAppointmentsView.as_view(), name="dashboard_appointments"),
    path(
        "appointments/all/",
        DashboardAllAppointmentsView.as_view(),
        name="dashboard_all_appointments",
    ),
    path(
        "appointments/cancelled/",
        DashboardCancelledView.as_view(),
        name="dashboard_cancelled_appointments",
    ),
    path("stats/", DashboardStatsView.as_view(), name="dashboard_stats"),
]
