import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from googleapiclient.errors import HttpError

from apps.calendar_app.models import ProviderSettings
from apps.calendar_app.utils import (
    _build_service,
    _get_admin_credential,
)
from common.selectors.base import BaseSelector

logger = logging.getLogger(__name__)


class AvailabilitySelector(BaseSelector):
    @classmethod
    def _get_work_hours(
        cls, query_date: date, ps: ProviderSettings
    ) -> tuple[datetime, datetime, timedelta] | None:
        tz = ZoneInfo(ps.timezone)
        weekday_str = str(query_date.weekday())
        day_schedule = ps.day_schedules.get(weekday_str)
        if not day_schedule or not day_schedule.get("is_active"):
            return None

        try:
            work_start = datetime.strptime(day_schedule["start"], "%H:%M").time()
            work_end = datetime.strptime(day_schedule["end"], "%H:%M").time()
        except (ValueError, KeyError):
            return None

        start_of_day = datetime.combine(query_date, work_start, tzinfo=tz)
        end_of_day = datetime.combine(query_date, work_end, tzinfo=tz)
        slot_delta = timedelta(minutes=ps.slot_duration)
        return start_of_day, end_of_day, slot_delta

    @classmethod
    def _fetch_google_freebusy(
        cls, provider: User, ps: ProviderSettings, start_of_day: datetime, end_of_day: datetime
    ) -> list[dict[str, Any]]:
        try:
            cred = _get_admin_credential(provider)
            service = _build_service(cred)
        except RuntimeError as exc:
            raise RuntimeError(str(exc)) from exc

        try:
            freebusy_result = (
                service.freebusy()
                .query(
                    body={
                        "timeMin": start_of_day.isoformat(),
                        "timeMax": end_of_day.isoformat(),
                        "timeZone": ps.timezone,
                        "items": [{"id": ps.calendar_id}],
                    }
                )
                .execute()
            )
        except HttpError as exc:
            logger.exception("freebusy failed: %s", exc)
            raise RuntimeError("Failed to fetch calendar availability.") from exc

        return freebusy_result.get("calendars", {}).get(ps.calendar_id, {}).get("busy", [])

    @classmethod
    def _get_break_intervals(
        cls, query_date: date, ps: ProviderSettings
    ) -> list[tuple[datetime, datetime]]:
        tz = ZoneInfo(ps.timezone)
        breaks = ps.break_times.filter(weekday=query_date.weekday())
        return [
            (
                datetime.combine(query_date, b.start, tzinfo=tz),
                datetime.combine(query_date, b.end, tzinfo=tz),
            )
            for b in breaks
        ]

    @classmethod
    def get_free_slots(cls, query_date: date, provider: User) -> tuple[list[dict[str, Any]], str]:
        ps = ProviderSettings.get_for_provider(provider)

        # 1. Holiday Check
        if ps.holidays.filter(date=query_date).exists():
            return [], ps.timezone

        # 2. Day Schedule Check
        work_hours = cls._get_work_hours(query_date, ps)
        if not work_hours:
            return [], ps.timezone

        start_of_day, end_of_day, slot_delta = work_hours

        # 3. Google Calendar FreeBusy Check
        busy_intervals = cls._fetch_google_freebusy(provider, ps, start_of_day, end_of_day)

        # 4. Custom Breaks Check
        break_intervals = cls._get_break_intervals(query_date, ps)

        def _is_free(slot_start: datetime, slot_end: datetime) -> bool:
            # Check Google Calendar busy intervals
            for b in busy_intervals:
                b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
                b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
                if slot_start < b_end and slot_end > b_start:
                    return False
            # Check custom Break Times
            for b_start, b_end in break_intervals:
                if slot_start < b_end and slot_end > b_start:
                    return False
            return True

        from django.utils.timezone import now

        from apps.calendar_app.models import SlotLock

        active_locked_starts = set(
            SlotLock.objects.filter(
                provider=provider,
                slot_start__date=query_date,
                expires_at__gt=now(),
                is_confirmed=False,
            ).values_list("slot_start", flat=True)
        )

        free_slots = []
        current = start_of_day
        while current + slot_delta <= end_of_day:
            slot_end = current + slot_delta
            if _is_free(current, slot_end) and current not in active_locked_starts:
                free_slots.append({"start": current, "end": slot_end})
            current = slot_end

        return free_slots, ps.timezone
