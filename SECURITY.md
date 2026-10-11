# Security Policy

## Scope

This repository contains only the deterministic decision-layer source,
synthetic fixtures, and documentation. It intentionally excludes credentials,
model weights, datasets, telemetry, and local infrastructure configuration
(see `.gitignore` and `README.md` privacy boundaries).

## Reporting a vulnerability

Please report suspected vulnerabilities via a private GitHub Security Advisory
for this repository (preferred) or a direct message to the maintainer. Do not
open a public issue with exploit details.

Include: affected file/commit, impact assessment, and reproduction steps using
only synthetic data. Please allow reasonable time for a fix before public
disclosure.

## Guarantees and non-guarantees

- The deterministic policy engine is fail-closed by design; defects in
  advisory backends must degrade to fallback, never to silent execution.
- Static workflow analysis and export sanitization are best-effort: exported
  templates may contain arbitrary upstream content. Review before importing
  anything into n8n.
- No secret-scanning gate is perfect. If you suspect a credential was
  committed, treat it as compromised, rotate it, and notify the maintainer.
