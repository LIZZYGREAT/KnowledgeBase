#!/usr/bin/env python3
"""KnowledgeBase validation and derived-index rebuild commands."""

import argparse
from pathlib import Path
import sqlite3
import sys
from typing import Optional

import yaml
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.db.connection import connect_database
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.import_repository import ImportRepository
from backend.app.services.draft_service import DraftService
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.git_manager import GitManager
from backend.app.services.import_service import ImportService
from backend.app.domain.source import SourceMetadata
from backend.app.domain.collection import Collection
from backend.app.domain.taxonomy import TaxonomyRegistry
from backend.app.services.indexer import IndexBuildError, Indexer
from backend.app.services.canonical_validator import validate_repository_references
from backend.app.services.markdown_parser import parse_markdown, parse_yaml
from backend.app.services.style_linter import (
    LintIssue,
    lint_markdown,
    load_writing_standard,
)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="kb", description="Validate canonical KnowledgeBase files.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="check canonical Markdown and YAML files")
    check.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="files or directories to check (defaults to ./knowledge)",
    )
    rebuild = commands.add_parser("rebuild", help="rebuild disposable search indexes from canonical files")
    rebuild.add_argument("--root", type=Path, default=ROOT, help="KnowledgeBase repository root")
    rebuild.add_argument(
        "--database",
        type=Path,
        help="Runtime SQLite path (defaults to <root>/runtime/knowledge.db)",
    )
    import_command = commands.add_parser(
        "import", help="stage Markdown and PDF files for review without publishing them"
    )
    import_command.add_argument("paths", nargs="+", type=Path, help="files or directories to stage")
    import_command.add_argument(
        "--profile", choices=("standard", "legacy"), default="standard",
        help="use legacy defaults for old Markdown notes",
    )
    import_command.add_argument("--root", type=Path, default=ROOT, help="KnowledgeBase repository root")
    import_command.add_argument("--database", type=Path, help="Runtime SQLite path")
    args = parser.parse_args(argv)

    if args.command == "check":
        paths = args.paths or [ROOT / "knowledge"]
        return check_paths(paths)
    if args.command == "rebuild":
        root = args.root.resolve()
        database_path = args.database or Path("runtime") / "knowledge.db"
        if not database_path.is_absolute():
            database_path = root / database_path
        connection = None
        try:
            connection = connect_database(database_path)
            summary = Indexer(root, connection).full_rebuild()
        except (IndexBuildError, OSError, ValueError, sqlite3.Error) as error:
            print("ERROR rebuild: {}".format(error))
            return 1
        finally:
            if connection is not None:
                connection.close()
        print(
            "Rebuilt indexes: {} documents, {} terms, {} aliases, {} taxonomy entries, "
            "{} collections, {} collection nodes, {} backlinks, {} evidence records, {} sources.".format(
                summary.documents,
                summary.terms,
                summary.aliases,
                summary.taxonomy_entries,
                summary.collections,
                summary.collection_nodes,
                summary.backlinks,
                summary.evidence,
                summary.sources,
            )
        )
        return 0
    if args.command == "import":
        root = args.root.resolve()
        database_path = args.database or Path("runtime") / "knowledge.db"
        if not database_path.is_absolute():
            database_path = root / database_path
        connection = None
        try:
            connection = connect_database(database_path)
            service = ImportService(
                root,
                ImportRepository(connection),
                DraftService(DraftRepository(connection)),
                GitManager(root),
                canonical_target_resolver=CanonicalTargetResolver(root, connection),
            )
            job = service.stage_paths(args.paths, profile=args.profile)
            items = service.get_items(job.id)
        except (OSError, ValueError, sqlite3.Error, RuntimeError) as error:
            print("ERROR import: {}".format(error))
            return 1
        finally:
            if connection is not None:
                connection.close()
        print("Import Job {} · {} · profile {}".format(job.id, job.status, job.profile))
        for item in items:
            print("{} {} · {} · {}".format(item.file_type, item.status, item.id, item.metadata.get("display_name", Path(item.path).name)))
        if job.error_message:
            print("NOTE {}".format(job.error_message))
        return 0 if job.status != "failed" else 1
    return 2


def check_paths(paths: list[Path]) -> int:
    standard = load_writing_standard()
    files = []
    canonical_scope = False
    knowledge_root = (ROOT / "knowledge").resolve()
    for supplied in paths:
        path = supplied if supplied.is_absolute() else ROOT / supplied
        if not path.exists():
            print("ERROR {}: path does not exist".format(path))
            return 1
        try:
            path.resolve().relative_to(knowledge_root)
            canonical_scope = True
        except ValueError:
            pass
        if path.resolve() == knowledge_root:
            canonical_scope = True
        if path.is_dir():
            files.extend(
                child
                for child in path.rglob("*")
                if child.is_file() and child.suffix.lower() in {".md", ".yaml", ".yml"}
            )
        else:
            files.append(path)

    failures = 0
    warnings = 0
    checked = 0
    for path in sorted(set(files)):
        checked += 1
        issues = check_file(path, standard)
        for issue in issues:
            if issue.severity == "ERROR":
                failures += 1
            else:
                warnings += 1
            print("{}:{}: {} [{}] {}".format(path, issue.line, issue.severity, issue.code, issue.message))

    if canonical_scope:
        for issue in validate_repository_references(ROOT):
            failures += 1
            print(
                "{}:{}: ERROR [{}] {}".format(
                    ROOT / issue.path, issue.line, issue.code, issue.message
                )
            )

    if failures:
        print(
            "Checked {} file(s); found {} error(s) and {} warning(s).".format(
                checked, failures, warnings
            )
        )
        return 1
    print(
        "Checked {} file(s); no errors and {} warning(s).".format(checked, warnings)
    )
    return 0


def check_file(path: Path, standard) -> list[LintIssue]:
    suffix = path.suffix.lower()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [LintIssue("file.read", str(error), 1)]

    canonical_relative = _canonical_relative_path(path)
    if suffix == ".md":
        parsed = parse_markdown(text)
        entity_type = _markdown_entity_type(path, parsed.frontmatter)
        issues = lint_markdown(text, entity_type=entity_type, standard=standard)
        if canonical_relative is not None and parsed.frontmatter is not None:
            issues.extend(_check_markdown_layout(path, canonical_relative, parsed.frontmatter, entity_type))
        return issues

    if suffix not in {".yaml", ".yml"}:
        return [LintIssue("file.extension", "Expected a .md, .yaml, or .yml file.", 1)]

    try:
        value = parse_yaml(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        return [LintIssue("yaml.syntax", str(error), mark.line + 1 if mark else 1)]
    if not isinstance(value, dict):
        return [LintIssue("yaml.mapping", "Canonical YAML must contain a mapping.", 1)]

    kind = _yaml_entity_type(path, value)
    try:
        if kind == "source":
            entity = SourceMetadata.model_validate(value)
        elif kind == "taxonomy":
            entity = TaxonomyRegistry.model_validate(value)
        elif kind == "collection":
            entity = Collection.model_validate(value)
        else:
            return [LintIssue("schema.entity_type", "Cannot identify this YAML as a Source, Taxonomy, or Collection registry.", 1)]
    except ValidationError as error:
        return [
            LintIssue(
                "schema.metadata",
                "metadata{}: {}".format(
                    "." + ".".join(str(part) for part in detail["loc"])
                    if detail["loc"]
                    else "",
                    detail["msg"],
                ),
                1,
            )
            for detail in error.errors()
        ]
    except ValueError as error:
        return [LintIssue("schema.metadata", str(error), 1)]

    if canonical_relative is not None:
        issues = _check_yaml_layout(path, canonical_relative, entity, kind)
        return issues
    return []


def _markdown_entity_type(path: Path, frontmatter: Optional[dict]) -> Optional[str]:
    relative = _canonical_relative_path(path)
    if relative:
        if relative.parts and relative.parts[0] == "documents":
            return "document"
        if relative.parts and relative.parts[0] == "terms":
            return "term"
    if frontmatter:
        value = frontmatter.get("type")
        if value in {"paper-note", "learning-note", "course-note"}:
            return "document"
        if value in {"concept", "vocabulary"}:
            return "term"
    return None


def _yaml_entity_type(path: Path, value: dict) -> Optional[str]:
    relative = _canonical_relative_path(path)
    if relative:
        if relative.parts[0] == "sources":
            return "source"
        if relative.parts[0] == "taxonomy":
            return "taxonomy"
        if relative.parts[0] == "collections":
            return "collection"
    if "entries" in value:
        return "taxonomy"
    if "nodes" in value:
        return "collection"
    if value.get("type") in {"paper", "book", "course", "web", "personal"}:
        return "source"
    return None


def _canonical_relative_path(path: Path):
    try:
        return path.resolve().relative_to((ROOT / "knowledge").resolve())
    except ValueError:
        return None


def _check_markdown_layout(path: Path, relative: Path, metadata: dict, entity_type: Optional[str]) -> list[LintIssue]:
    issues = []
    entity_id = metadata.get("id")
    if isinstance(entity_id, str) and path.stem != entity_id:
        issues.append(LintIssue("path.id", "File name must match the canonical id '{}'.".format(entity_id), 1))

    if entity_type == "document":
        expected_directory = {
            "paper-note": "papers",
            "learning-note": "learning",
            "course-note": "courses",
        }.get(metadata.get("type"))
        if expected_directory and (
            len(relative.parts) != 3
            or relative.parts[0] != "documents"
            or relative.parts[1] != expected_directory
        ):
            issues.append(
                LintIssue(
                    "path.document_type",
                    "Document type '{}' belongs under documents/{}.".format(
                        metadata.get("type"), expected_directory
                    ),
                    1,
                )
            )
    if entity_type == "term" and (len(relative.parts) != 2 or relative.parts[0] != "terms"):
        issues.append(LintIssue("path.term", "Terms must be stored directly under knowledge/terms/.", 1))
    return issues


def _check_yaml_layout(path: Path, relative: Path, entity, kind: str) -> list[LintIssue]:
    issues = []
    if kind == "source":
        if path.stem != entity.id:
            issues.append(LintIssue("path.id", "File name must match the canonical id '{}'.".format(entity.id), 1))
        if relative.parts[0] != "sources" or len(relative.parts) != 2 or path.suffix.lower() != ".yaml":
            issues.append(LintIssue("path.source", "Sources must be stored as knowledge/sources/<id>.yaml.", 1))
    if kind == "taxonomy":
        if (
            path.name not in {"domains.yaml", "topics.yaml", "tags.yaml"}
            or relative.parts[0] != "taxonomy"
            or len(relative.parts) != 2
        ):
            issues.append(LintIssue("path.taxonomy", "Taxonomy registries must be stored as knowledge/taxonomy/{domains,topics,tags}.yaml.", 1))
    if kind == "collection":
        if (
            len(relative.parts) != 2
            or relative.parts[0] != "collections"
            or path.stem != entity.id
            or path.suffix.lower() != ".yaml"
        ):
            issues.append(
                LintIssue(
                    "path.collection",
                    "Collections must be stored as knowledge/collections/<id>.yaml.",
                    1,
                )
            )
    return issues


if __name__ == "__main__":
    raise SystemExit(main())
