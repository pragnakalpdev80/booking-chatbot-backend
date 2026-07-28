from unittest.mock import MagicMock, patch

import pytest

from apps.calendar_app.models import GoogleCredential
from apps.calendar_app.utils import _build_service, _get_admin_credential, _get_flow


@pytest.mark.django_db
class TestCalendarUtils:
    def test_get_admin_credential_success(self, user):
        cred = GoogleCredential(user=user)
        cred.set_token(
            '{"token": "token", "refresh_token": "refresh", "client_id": "client", "client_secret": "secret", "token_uri": "uri"}'  # noqa: E501
        )
        cred.save()
        cred = _get_admin_credential(user)
        import json

        assert json.loads(cred.get_token_json())["token"] == "token"

    def test_get_admin_credential_missing(self, user):
        with pytest.raises(RuntimeError):
            _get_admin_credential(user)

    @patch("apps.calendar_app.utils.Flow.from_client_config")
    def test_get_flow(self, mock_from_client_config):
        _get_flow("http://localhost:8000/callback")
        mock_from_client_config.assert_called_once()

    @patch("apps.calendar_app.models.GoogleCredential.get_credentials")
    @patch("apps.calendar_app.utils.build")
    def test_build_service(self, mock_build, mock_get_credentials, user):
        mock_creds = MagicMock()
        mock_get_credentials.return_value = mock_creds
        cred = GoogleCredential(user=user)
        cred.set_token(
            '{"token": "token", "refresh_token": "refresh", "client_id": "client", "client_secret": "secret", "token_uri": "uri"}'  # noqa: E501
        )
        cred.save()
        cred = _get_admin_credential(user)
        _build_service(cred)
        mock_build.assert_called_once_with("calendar", "v3", credentials=mock_creds)
