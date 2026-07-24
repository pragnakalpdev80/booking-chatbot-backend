import logging
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from googleapiclient.errors import HttpError

from apps.calendar_app.models import ProviderSettings
from apps.calendar_app.utils import (
    SLOT_DURATION_MINUTES,
    _build_service,
    _get_admin_credential,
)
from common.selectors.base import BaseSelector

logger = logging.getLogger(__name__)


class AvailabilitySelector(BaseSelector):
    @classmethod
    def get_free_slots(cls, query_date: date, provider: User) -> tuple[list[dict[str, Any]], str]:
        ps = ProviderSettings.get_for_provider(provider)
        tz = ZoneInfo(ps.timezone)

        if query_date.weekday() not in (ps.work_days or [0, 1, 2, 3, 4]):
            return [], ps.timezone

        start_of_day = datetime.combine(query_date, ps.work_start, tzinfo=tz)
        end_of_day = datetime.combine(query_date, ps.work_end, tzinfo=tz)
        slot_delta = timedelta(minutes=SLOT_DURATION_MINUTES)

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

        busy_intervals = (
            freebusy_result.get("calendars", {}).get(ps.calendar_id, {}).get("busy", [])
        )

        def _is_free(slot_start: datetime, slot_end: datetime) -> bool:
            for b in busy_intervals:
                b_start = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
                b_end = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
                # Overlap check
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
                free_slots.append(
                    {
                        "start": current,
                        "end": slot_end,
                    }
                )
            current = slot_end

        return free_slots, ps.timezone
