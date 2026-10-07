# Import workflow

Markdown and PDF imports follow a review-first path:

```text
Input → Staging → Hash / Metadata Parse → Resolver → Deterministic Lint
      → Manual Review → Draft → Publisher
```

## Stage local uploads

Open Library → Import to stage multiple `.md` and `.pdf` files from the browser through file selection or drag-and-drop. The temporary browser upload is copied into Import Pipeline staging and then removed. The Advanced server-path form and API accept paths beneath `storage/uploads/`; absolute paths, parent traversal, and symbolic links are rejected. Markdown and PDF files can be staged together, SHA-256 duplicates are reported, and matching Markdown/PDF names are suggested as a bundle.

The command-line entry point can stage files from any readable local path:

```sh
python tools/kb.py import <file-or-directory> [<another-path> ...] --profile legacy
```

Use `--profile legacy` for older notes. The import service still does not write canonical files or call AI. In production, Compose mounts the configured `KB_IMPORT_DIRECTORY` read-only at `/imports` for CLI batch staging.

## Review Markdown

Open the staged item from Library → Import and inspect its content. Standard imports require valid canonical Frontmatter before a Document or Term Draft can be created. With the Legacy profile, an older Markdown file may omit Frontmatter; Draft creation synthesizes minimal metadata, sets human review to `unreviewed` and maintenance to `legacy`, and preserves the original body. Review the generated metadata and refine it when needed. Writing-style findings remain review information; structural and schema errors still block publishing.

After the Draft exists, the editor can request a DeepSeek metadata Proposal. The user must explicitly consent to send the Draft and required registry context. The result is stored as a Proposal; its suggested fields enter the Draft only after a human selects the apply action. Publishing remains a separate Publisher action.

## Review PDFs

PDF-only items never become Notes. Confirm the Source ID, title, and type while reviewing the staged item; the workflow creates a Source Draft and copies the PDF into ignored `storage/papers/`. The Source metadata is published only through Publisher. Existing Sources resolve deterministically by identifier and then title; ambiguous candidates require explicit selection.

Staged input and Import Jobs remain in ignored `storage/` and Runtime SQLite. The runtime database and storage directory are included in the Phase 12 production backup archive.
