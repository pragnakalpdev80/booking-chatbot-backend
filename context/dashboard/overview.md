# Context — `apps/dashboard/`

## Purpose

The `dashboard` app provides read-only aggregation endpoints specifically tailored for the React frontend's Admin Dashboard. It surfaces metrics and tabular appointment data for the provider.

## Key Models

- None. This app does not persist data; it aggregates existing data primarily from `calendar_app.Booking` and `calendar_app.ProviderSettings`.

## Key Endpoints (`/api/dashboard/`)

- `GET /appointments/` (`DashboardAppointmentsView`) — Returns upcoming active appointments for the provider, heavily optimized with prefetching.
- `GET /appointments/all/` (`DashboardAllAppointmentsView`) — Returns paginated historical and future appointments for the Data Table. Allows searching and filtering.
- `GET /appointments/cancelled/` (`DashboardCancelledView`) — Returns only cancelled appointments.
- `GET /stats/` (`DashboardStatsView`) — Computes high-level KPI cards (Total Bookings, Cancelled Bookings, Estimated Revenue) by aggregating `Booking` and `PaymentOrder` data within the current month.

## Design Decisions

- **Performance Over Normalization**: By creating dedicated views here instead of reusing standard ListViews in `calendar_app`, we can optimize SQL queries (aggregations, annotations, and prefetches) specifically for the heavy load of a dashboard without polluting the core logic of the calendar engine.
