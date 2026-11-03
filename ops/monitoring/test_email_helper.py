from unittest.mock import Mock, patch

import pytest
import requests

from ops.monitoring.email_helper import EmailError, send_email


@pytest.fixture(autouse=True)
def config(monkeypatch):
    for name in ("CF_ACCOUNT_ID", "CF_EMAIL_API_TOKEN", "CF_EMAIL_FROM", "CF_EMAIL_TO"):
        monkeypatch.setenv(name, "test")


@pytest.mark.parametrize("status", ["delivered", "queued"])
def test_accepted(status):
    response = Mock(ok=True)
    response.json.return_value = {"success": True, "result": {status: ["test"]}}
    with patch("ops.monitoring.email_helper.requests.post", return_value=response) as post:
        assert send_email("subject", "body") == status
        assert post.call_args.kwargs["timeout"] == 30


@pytest.mark.parametrize("payload", [
    {"success": False}, {"success": True, "result": {}},
    {"success": True, "result": {"permanent_bounces": ["test"]}},
    {"success": True, "errors": ["rejected"]}, None,
])
def test_rejected(payload):
    response = Mock(ok=True)
    response.json.return_value = payload
    with patch("ops.monitoring.email_helper.requests.post", return_value=response):
        with pytest.raises(EmailError):
            send_email("subject", "body")


def test_transport_failure():
    with patch("ops.monitoring.email_helper.requests.post", side_effect=requests.Timeout("secret")):
        with pytest.raises(EmailError, match="^Cloudflare email request failed$"):
            send_email("subject", "body")


def test_http_failure():
    with patch("ops.monitoring.email_helper.requests.post", return_value=Mock(ok=False, status_code=403)):
        with pytest.raises(EmailError, match="HTTP 403"):
            send_email("subject", "body")


def test_missing_config(monkeypatch):
    monkeypatch.delenv("CF_EMAIL_API_TOKEN")
    with pytest.raises(EmailError, match="CF_EMAIL_API_TOKEN"):
        send_email("subject", "body")
