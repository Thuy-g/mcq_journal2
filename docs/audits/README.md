# Audit Directory

Store dated technical audits here.

Naming convention:

```text
AUDIT_<scope>_<version>_<YYYY-MM-DD>.md
```

Current expected file:

```text
AUDIT_Journal2_v2_2026-07-26.md
```

Create and verify a checksum:

```bash
sha256sum AUDIT_Journal2_v2_2026-07-26.md \
  > AUDIT_Journal2_v2_2026-07-26.md.sha256

sha256sum -c AUDIT_Journal2_v2_2026-07-26.md.sha256
```

Audits are evidence and planning documents. They do not replace:

- source-code inspection;
- unit tests;
- regression tests;
- primary-paper verification;
- real batch experiments.

Never edit an archived audit silently. Create a new dated audit or an explicitly labeled amendment.
