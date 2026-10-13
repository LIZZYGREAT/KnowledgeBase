# Writing standard

The machine-readable rules live in [`config/writing-standard.yaml`](../config/writing-standard.yaml).

- Exactly one unnumbered H1 per canonical Markdown file.
- H2 headings use Chinese numeral prefixes such as `一、`.
- H3 headings use Arabic numbering with one space after the period, such as `1. 标题`.
- H4 and H5 are unnumbered; headings deeper than H5 produce a style reminder.
- Inline math uses `$...$`; display math uses `$$...$$`.
- Wiki links use `[[term-id]]` or `[[term-id|display text]]`.
- Citation markers use `[@source-id]` with an optional locator.
- Mermaid blocks must contain non-comment content. The frontend renderer reports Mermaid syntax errors; the backend does not maintain a diagram-type whitelist.

The deterministic linter retains all findings. Heading count, numbering, ordinary hierarchy and empty Mermaid blocks are **warnings**, for both current and legacy content. These reminders do not block Import, preflight, single/batch Publish or Restore; publishing does not silently rewrite the body. The YAML configuration remains the preferred style, not a data-integrity gate.

Malformed frontmatter or required metadata, unsafe/unclosed code and math boundaries, malformed links, ambiguous references, missing Source/Taxonomy/Collection targets, invalid paths/IDs and version conflicts **block** publication. Preflight and publication use the same backend classification. AI bilingual Term output must preserve the ID/type/depth and exactly one Chinese and one English section. Generated real H3 headings use the existing safe normalization; fenced examples are left intact. No bulk conversion to legacy or rewriting of existing explanations is performed.
