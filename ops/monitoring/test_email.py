"""Explicitly invoke with python -m ops.monitoring.test_email."""

from ops.monitoring.email_helper import EmailError, send_email


def main():
    try:
        status = send_email(
            "ercotstress: email delivery test",
            "Cloudflare email delivery test from ercotstress. Confirm receipt in Gmail before enabling monitoring.",
        )
    except EmailError as exc:
        print(str(exc))
        return 1
    print(f"Email {status}; confirm receipt in Gmail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
