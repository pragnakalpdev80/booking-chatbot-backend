import logging
from datetime import datetime

from django.conf import settings
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from apps.calendar_app.models import GoogleCredential

logger = logging.getLogger(__name__)

SLOT_DURATION_MINUTES = 30
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_flow(state=None) -> Flow:
    kwargs = {
        "scopes": SCOPES,
        "redirect_uri": getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", ""),
    }
    if state:
        kwargs["state"] = state
    return Flow.from_client_secrets_file(
        getattr(settings, "GOOGLE_CLIENT_SECRETS_FILE", ""), **kwargs
    )


def _get_admin_credential(provider_user) -> GoogleCredential:
    try:
        return GoogleCredential.objects.select_related("user").get(user=provider_user)
    except GoogleCredential.DoesNotExist:
        raise RuntimeError(
            "This provider has not connected their Google Calendar yet. "
            "An admin must complete the OAuth flow first."
        ) from None


def _build_service(credential: GoogleCredential):
    creds = credential.get_credentials()
    return build("calendar", "v3", credentials=creds)


def _check_freebusy(service, start_dt: datetime, end_dt: datetime, calendar_id: str) -> bool:
    body = {
        "timeMin": start_dt.isoformat(),
        "timeMax": end_dt.isoformat(),
        "items": [{"id": calendar_id}],
    }
    try:
        result = service.freebusy().query(body=body).execute()
        busy_slots = result.get("calendars", {}).get(calendar_id, {}).get("busy", [])
        return len(busy_slots) == 0
    except HttpError as exc:
        logger.exception("freebusy check failed: %s", exc)
        raise RuntimeError(f"Could not check calendar availability: {exc}") from exc
