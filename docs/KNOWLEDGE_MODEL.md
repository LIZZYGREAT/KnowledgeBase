# Canonical knowledge model

## Entities

- **Document**: a complete note with type `paper-note`, `learning-note`, or `course-note`.
- **Term**: a reusable knowledge node with type `concept` or `vocabulary`, and depth `stub`, `standard`, or `deep`.
- **Source**: a source record with type `paper`, `book`, `course`, `web`, or `personal`.
- **Taxonomy**: canonical Domain, Topic, and Tag registries. Documents reference IDs; definitions live in the registries.

Canonical documents and terms are Markdown files with YAML frontmatter. Sources and taxonomy registries are YAML files. IDs are stable lowercase slugs. Formal metadata types are defined in `backend/app/domain/`.

## Review and maintenance

AI review states are `not_run`, `passed`, `needs_attention`, and `failed`. Human review states are `unreviewed`, `approved`, and `rejected`. Maintenance states are `current`, `needs_revision`, and `legacy`.

This phase validates entity shape only. Cross-file ID resolution and alias ambiguity checks belong to Phase 2.
