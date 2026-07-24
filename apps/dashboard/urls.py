from django.urls import path

from .views import DashboardAppointmentsView, DashboardStatsView

urlpatterns = [
    path("appointments/", DashboardAppointmentsView.as_view(), name="dashboard_appointments"),
    path("stats/", DashboardStatsView.as_view(), name="dashboard_stats"),
]
