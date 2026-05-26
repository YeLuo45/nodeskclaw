import json
import os
from urllib import request

url = os.environ.get("DESKCLAW_TRUSTED_OAUTH_EXCHANGE_URL", "").strip()
token_ref = os.environ.get("OAUTH_TOKEN_REF", "").strip()
access_token = os.environ.get("OAUTH_ACCESS_TOKEN", "").strip()

if not url:
    raise SystemExit("missing DESKCLAW_TRUSTED_OAUTH_EXCHANGE_URL")
if not token_ref:
    raise SystemExit("missing OAUTH_TOKEN_REF")
if not access_token:
    raise SystemExit("missing OAUTH_ACCESS_TOKEN")

req = request.Request(
    url,
    headers={
        "Authorization": f"Bearer {access_token}",
        "X-Token-Ref": token_ref,
        "Accept": "application/json",
    },
)

with request.urlopen(req, timeout=15) as resp:
    body = resp.read().decode("utf-8")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = {"raw": body}

print(json.dumps({
    "ok": 200 <= resp.status < 300,
    "status": resp.status,
    "token_ref": token_ref,
    "broker": payload,
}, ensure_ascii=False))
