---
name: agent-asset-vetting
description: Evaluate third-party skills, MCPs, plugins, hooks, agents and harnesses for provenance, permissions, maturity, overlap and measurable value before FlowOps adoption.
---

# Agent asset vetting

Before adoption: verify source and license; inspect requested filesystem/shell/network/secret permissions; review install/postinstall/dynamic-download behavior; assess injection/exfiltration and dependency risk; compare with existing local capabilities; sandbox when executable; and decide `ADOPT`, `ADAPT`, `POC`, `REJECT` or `SUPERSEDED`.

Popularity is discovery evidence, never authorization. Prefer a small auditable adaptation when importing the implementation adds unnecessary attack surface or lock-in.
