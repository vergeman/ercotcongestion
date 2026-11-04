"""Send plain-text monitoring email through Cloudflare."""

import os

import requests


class EmailError(RuntimeError):
    pass


def send_email(subject, body):
    names = ("CF_ACCOUNT_ID", "CF_EMAIL_API_TOKEN", "CF_EMAIL_FROM", "CF_EMAIL_TO")
    config = {name: os.environ.get(name, "").strip() for name in names}
    missing = [name for name, value in config.items() if not value]
    if missing:
        raise EmailError("Missing email configuration: " + ", ".join(missing))
    try:
        response = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{config['CF_ACCOUNT_ID']}/email/sending/send",
            headers={"Authorization": f"Bearer {config['CF_EMAIL_API_TOKEN']}"},
            json={"from": config["CF_EMAIL_FROM"], "to": config["CF_EMAIL_TO"],
                  "subject": subject, "text": body},
            timeout=30,
        )
    except requests.RequestException:
        raise EmailError("Cloudflare email request failed") from None
    if not response.ok:
        raise EmailError(f"Cloudflare email HTTP {response.status_code}")
    try:
        payload = response.json()
        result = payload.get("result") or {}
        accepted = result.get("delivered", []) + result.get("queued", [])
        if (payload.get("success") is not True or payload.get("errors")
                or result.get("permanent_bounces") or config["CF_EMAIL_TO"] not in accepted):
            raise EmailError("Cloudflare rejected or bounced the email")
    except (ValueError, TypeError, AttributeError):
        raise EmailError("Invalid Cloudflare email response") from None
    return "delivered" if config["CF_EMAIL_TO"] in result.get("delivered", []) else "queued"
