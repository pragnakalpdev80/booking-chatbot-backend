import datetime

from googleapiclient.discovery import build

from apps.calendar_app.models import GoogleCredential


def get_gcal_service(provider):
    try:
        credential = GoogleCredential.objects.select_related("user").get(user=provider)
    except GoogleCredential.DoesNotExist:
        raise ValueError(
            "The administrator has not linked their Google Calendar yet. "
            "Tell the user that the booking service is currently unavailable."
        ) from None
    creds = credential.get_credentials()
    return build("calendar", "v3", credentials=creds)


def check_freebusy(
    service, start_dt: datetime.datetime, end_dt: datetime.datetime, calendar_id: str
) -> bool:
    body = {
        "timeMin": start_dt.isoformat(),
        "timeMax": end_dt.isoformat(),
        "items": [{"id": calendar_id}],
    }
    result = service.freebusy().query(body=body).execute()
    busy = result.get("calendars", {}).get(calendar_id, {}).get("busy", [])
    return len(busy) == 0
