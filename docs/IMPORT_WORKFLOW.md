# Import workflow

Import is not implemented in the current phase. The planned path is:

```text
Input → Staging → Hash / Metadata Parse → Resolver → Deterministic Lint
      → Proposal Review → Publish
```

Markdown imports become Document candidates. PDF-only imports create Source candidates and must not automatically create paper notes. Uploaded and staged files stay under `storage/` and are excluded from Git. Import adapters and review workflows belong to later phases.
