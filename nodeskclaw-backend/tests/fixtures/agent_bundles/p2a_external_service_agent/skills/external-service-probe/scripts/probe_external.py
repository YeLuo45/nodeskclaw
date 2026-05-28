import json
import os
import urllib.parse
import urllib.request


base = os.environ.get("EXTERNAL_API_BASE", "").rstrip("/")
path = os.environ.get("EXTERNAL_API_PATH", "/get")
if not base:
    raise SystemExit("missing EXTERNAL_API_BASE")
if not path.startswith("/"):
    path = f"/{path}"

url = f"{base}{path}"
separator = "&" if "?" in url else "?"
url = f"{url}{separator}{urllib.parse.urlencode({'source': 'nodeskclaw-agent-bundle'})}"
request = urllib.request.Request(url, headers={"user-agent": "nodeskclaw-external-probe/1.0"})

with urllib.request.urlopen(request, timeout=10) as response:
    payload = response.read(64 * 1024).decode("utf-8", errors="replace")
    try:
        body = json.loads(payload)
    except json.JSONDecodeError:
        body = {"raw": payload[:512]}

print(json.dumps({
    "ok": 200 <= response.status < 300,
    "status": response.status,
    "url": url,
    "path": body.get("path") or body.get("url") or "",
    "raw": body.get("raw", "")[:120],
}, ensure_ascii=False))
