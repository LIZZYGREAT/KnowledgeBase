# Repository instructions

## Scope

- Implement only the current phase in `docs/ARCHITECTURE.md`; do not add Later features.
- Treat canonical Markdown and YAML as the knowledge source. Runtime and derived files must remain rebuildable.
- `Publisher` is the only business service that writes canonical knowledge. The frontend, AI, and indexers must not bypass it.
- Keep deterministic parsing and linting independent of HTTP, Git, SQLite, and AI.
- Keep `docs/private/` local and untracked. Do not copy its source specifications into commits.

## Implementation

- Read the relevant project docs and inspect the current tree and Git status before editing.
- Keep modules focused; add dependencies only when the existing stack cannot meet the phase requirements.
- Do not add compatibility layers or Later functionality.
- Preserve existing user files and configuration unless the task requires changing them.

## Validation and delivery

- Add or update focused tests for each completed feature and run the current phase checks.
- Before committing, review `git status --short`, run `git diff --check`, and ensure secrets, local databases, uploads, and build output are excluded.
- Report the files changed, behavior delivered, checks run and results, and known limitations.
