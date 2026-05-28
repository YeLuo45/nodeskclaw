---
name: oauth-probe
version: 1.0.0
description: Checks mock OAuth broker access through tokenRef
permissions:
  tools: ["http"]
  env: ["DESKCLAW_TRUSTED_OAUTH_EXCHANGE_URL", "OAUTH_TOKEN_REF", "OAUTH_ACCESS_TOKEN"]
scripts:
  probe: scripts/probe_oauth.py
---

# OAuth Probe

Call the mock broker using the provided token reference.
