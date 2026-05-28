---
name: external-service-probe
version: 1.0.0
description: Calls a configured external HTTP service from a bundled skill
scripts:
  probe: scripts/probe_external.py
permissions:
  tools: ["bash_tool", "http"]
  env: ["EXTERNAL_API_BASE", "EXTERNAL_API_PATH"]
---

# External Service Probe

Run `scripts/probe_external.py` to call the service configured by `EXTERNAL_API_BASE` and `EXTERNAL_API_PATH`.
