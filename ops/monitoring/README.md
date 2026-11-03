# Pipeline monitoring

## Email delivery test

Configure Cloudflare Email Sending for your sender domain and verify the Gmail
recipient in Email Routing. Create an account API token with email sending
permission for that account. The live test establishes whether the account is
eligible to send; HTTP 403 can indicate missing permission or entitlement.

API reference: https://developers.cloudflare.com/email-service/api/send-emails/rest-api/
Recipient setup: https://developers.cloudflare.com/email-service/configuration/email-routing-addresses/

Create a local, private env file outside the repository containing:

```text
CF_ACCOUNT_ID=your-account-id
CF_EMAIL_API_TOKEN=your-token
CF_EMAIL_FROM=alerts@your-domain
CF_EMAIL_TO=your-verified-address@gmail.com
```

Create the cluster Secret without putting credentials in command arguments:

```sh
kubectl -n ercotstress create secret generic monitoring-email \
  --from-env-file=/path/to/private-email.env
```

Run the test in an existing compute-shell pod. This copies only the two test
modules, so no image release is needed. Substitute the pod name if necessary.
The shell must have Python and requests installed.

```sh
kubectl -n ercotstress exec compute-shell -- mkdir -p /tmp/email-test
kubectl -n ercotstress cp ops/monitoring/email_helper.py compute-shell:/tmp/email-test/email_helper.py
kubectl -n ercotstress get secret monitoring-email -o json |
  kubectl -n ercotstress exec -i compute-shell -- python -c '
import base64, json, os, sys
config = json.load(sys.stdin)["data"]
for key in ("CF_ACCOUNT_ID", "CF_EMAIL_API_TOKEN", "CF_EMAIL_FROM", "CF_EMAIL_TO"):
    os.environ[key] = base64.b64decode(config[key]).decode()
sys.path.insert(0, "/tmp/email-test")
from email_helper import send_email
print(send_email("ercotstress: email delivery test", "Confirm receipt in Gmail before enabling monitoring."))
'
```

Alternatively, in an image containing this directory with the Secret mounted as
environment variables, run `python -m ops.monitoring.test_email`.

Confirm actual receipt in Gmail, including checking spam. A queued API response
alone does not establish inbox delivery. If the API rejects the request, inspect
Cloudflare account permissions, sender configuration, recipient verification, and
Email Sending entitlement before retrying. Do not paste tokens into logs or chat.

Run focused tests with:

```sh
python -m pytest ops/monitoring/test_email_helper.py -q
```

Preflight and watchdog implementation follows after confirmed email delivery.
