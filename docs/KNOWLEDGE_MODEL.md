# Canonical knowledge model

## Entities

- **Document**: a complete note with type `paper-note`, `learning-note`, or `course-note`.
- **Term**: a reusable knowledge node with type `concept` or `vocabulary`, and depth `stub`, `standard`, or `deep`.
- **Source**: a source record with type `paper`, `book`, `course`, `web`, or `personal`.
- **Taxonomy**: canonical Domain, Topic, and Tag registries. Documents and Terms reference IDs; definitions and aliases live in the registries.

Canonical documents and terms are Markdown files with YAML frontmatter. Sources and taxonomy registries are YAML files. IDs are stable lowercase slugs. Formal metadata types are defined in `backend/app/domain/`.

## Resolution and consistency

Term, Source, and Taxonomy resolvers match canonical IDs, titles, and aliases. Taxonomy aliases are optional and default to an empty list. Unresolved wiki links may remain in canonical Markdown; ambiguous wiki links, missing Source references, and missing taxonomy IDs fail Publish. `python tools/kb.py check` checks these references across the repository.

## Review and maintenance

AI review states are `not_run`, `passed`, `needs_attention`, and `failed`. Human review states are `unreviewed`, `approved`, and `rejected`. Maintenance states are `current`, `needs_revision`, and `legacy`.

Current Documents must pass the Writing Standard at Publish. Legacy Documents may publish with style warnings, but invalid frontmatter and other structural errors remain blocking. Import records style findings in its Runtime Item so the content can enter a Draft before those findings are resolved.

Draft conflict detection compares the target file's content hash. Its Git revision remains available as history and diff context. Proposals store `base_content_hash` and become stale only when their target content changes.

Provenance `origin` is either `imported` or `human-authored`. AI assistance is recorded separately and does not make AI the canonical author.
