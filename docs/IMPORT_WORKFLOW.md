# Import workflow

Phase 6 implements a local, review-first Markdown and PDF import workflow:

```text
Input → Staging → Hash / Metadata Parse → Resolver → Deterministic Lint
      → Draft → Manual Review and Edit → Publish
```

Markdown imports become Document or Term candidates. Valid canonical metadata is required to create a Draft; writing-style findings are retained on the Import Item and do not block that Draft. Current Documents still have to pass the Writing Standard at Publish. Legacy Documents can publish with style warnings, while broken frontmatter and other structural errors remain blocking.

PDF-only imports create Source Drafts and never automatically create paper notes. Existing Sources are matched by identifiers first and title second; ambiguous matches require an explicit selection. A local PDF is stored under `storage/papers/`, excluded from Git, and checked by Publisher before the Source metadata is committed. Markdown/PDF bundle associations remain suggestions until explicitly confirmed.

Staged files and Import Jobs live under ignored `storage/` and Runtime SQLite. Import does not write canonical files directly and does not call AI. API and Reference Hub workflows belong to later phases.

SHA-256 duplicates are blocked when the same content is already canonical or appears earlier in the same Import Job. A separate Job may stage the file again until its content has been published.
