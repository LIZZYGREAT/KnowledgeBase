# Writing standard

The machine-readable rules live in [`config/writing-standard.yaml`](../config/writing-standard.yaml).

- Exactly one unnumbered H1 per canonical Markdown file.
- H2 headings use Chinese numeral prefixes such as `一、`.
- H3 headings use Arabic numbering with one space after the period, such as `1. 标题`.
- H4 and H5 are unnumbered; headings deeper than H5 are errors.
- Inline math uses `$...$`; display math uses `$$...$$`.
- Wiki links use `[[term-id]]` or `[[term-id|display text]]`.
- Citation markers use `[@source-id]` with an optional locator.
- Mermaid blocks receive basic declaration checks; full Mermaid rendering is a later phase.

The deterministic linter reports structural and writing-style findings. Current Markdown style findings are errors at Publish. For Documents marked `maintenance.status: legacy`, heading and Mermaid style findings are warnings; malformed frontmatter, unclosed code or math blocks, and malformed wiki-link syntax remain errors. Semantic style suggestions and automatic rewriting are out of scope.
