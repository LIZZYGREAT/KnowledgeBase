#!/usr/bin/env bash
set -Eeuo pipefail

# Operator-only production reset. Copy to /tmp/kb_term_test_reset.sh, then run
# from /srv/KnowledgeBase. This script must never be run by Codex or locally.

readonly EXPECTED_ROOT="/srv/KnowledgeBase"
readonly CONFIRMATION="RESET_TEST_TERMS"
readonly SCHEMA_VERSION="19"
readonly RESEARCH_TIMER="knowledgebase-research.timer"
readonly RESEARCH_SERVICE="knowledgebase-research.service"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "$(pwd -P)" == "$EXPECTED_ROOT" ]] || fail "run this script from $EXPECTED_ROOT"
command -v git >/dev/null 2>&1 || fail "git is required"
command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v systemctl >/dev/null 2>&1 || fail "systemctl is required for the production Research guard"
command -v flock >/dev/null 2>&1 || fail "flock is required to coordinate with Research"
command -v find >/dev/null 2>&1 || fail "find is required"
[[ -f .env ]] || fail "production .env is missing"
[[ -f runtime/knowledge.db ]] || fail "Runtime database is missing"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "current directory is not a Git checkout"
[[ "$ROOT" == "$EXPECTED_ROOT" ]] || fail "Git checkout root is $ROOT, expected $EXPECTED_ROOT"

compose() {
  docker compose --env-file .env -f docker-compose.production.yml "$@"
}

dirty_status="$(git -C "$ROOT" status --porcelain --untracked-files=all)"
[[ -z "$dirty_status" ]] || {
  printf '%s\n' "$dirty_status" >&2
  fail "Git worktree must be clean"
}

if systemctl is-active --quiet "$RESEARCH_TIMER"; then
  fail "$RESEARCH_TIMER is active; stop it and verify it is inactive before retrying"
fi
if systemctl is-active --quiet "$RESEARCH_SERVICE"; then
  fail "$RESEARCH_SERVICE is active; wait for it to finish before retrying"
fi

terms_root="$ROOT/knowledge/terms"
if [[ -L "$terms_root" ]]; then
  fail "knowledge/terms must not be a symlink"
fi
if [[ -e "$terms_root" && ! -d "$terms_root" ]]; then
  fail "knowledge/terms exists but is not a directory"
fi
if [[ -d "$terms_root" ]]; then
  canonical_terms="$(find -L "$terms_root" -type f \( -iname '*.md' -o -iname '*.yaml' -o -iname '*.yml' \) -print)"
  [[ -z "$canonical_terms" ]] || {
    printf '%s\n' "$canonical_terms" >&2
    fail "published Term Markdown/YAML exists; canonical knowledge must not be removed by this script"
  }
fi

schema_version="$(compose run --rm --no-deps -T -w /workspace --entrypoint python backend -c 'import os, sqlite3; p=os.environ["DATABASE_PATH"]; c=sqlite3.connect("file:"+p+"?mode=ro", uri=True); print(c.execute("PRAGMA user_version").fetchone()[0]); c.close()')"
[[ "$schema_version" == "$SCHEMA_VERSION" ]] || fail "Runtime schema is $schema_version; expected $SCHEMA_VERSION"

# Canonical Collection YAML is preserved and rebuilt. Stop before mutation if it
# still contains Term references that would immediately repopulate the index.
compose run --rm --no-deps -T -w /workspace --entrypoint python backend - <<'PY'
from pathlib import Path
import sys

from backend.app.domain.collection import EntityNode, SectionNode
from backend.app.services.collection_registry import CollectionRegistry

root = Path("/workspace")
registry = CollectionRegistry.load(root / "knowledge" / "collections")
references = []

def visit(collection_id, nodes):
    for node in nodes:
        if isinstance(node, EntityNode) and node.entity_type == "term":
            references.append((collection_id, node.id, node.entity_id))
        elif isinstance(node, SectionNode):
            visit(collection_id, node.children)

for collection in registry.collections:
    visit(collection.id, collection.nodes)

if references:
    for collection_id, node_id, term_id in references:
        print("Term reference in canonical Collection {}: node {} -> {}".format(
            collection_id, node_id, term_id
        ), file=sys.stderr)
    raise SystemExit("canonical Collection references must be reviewed before the Term reset")
PY

printf '\nThis will delete Term-only Runtime candidates, proposals, caches, relations, annotations and history.\n'
printf 'Canonical knowledge, Research, Imports, uploaded files and non-Term Drafts/Proposals are preserved.\n'
printf 'A verified production backup will be created before deletion. This operation is irreversible.\n'
printf 'Type %s to continue: ' "$CONFIRMATION"
IFS= read -r confirmation
[[ "$confirmation" == "$CONFIRMATION" ]] || fail "confirmation did not match; no data was changed"

mkdir -p runtime
exec 9>>runtime/research.lock
flock -n 9 || fail "a Research run holds runtime/research.lock; wait for it to finish"
exec 8>>runtime/term-discovery.lock
flock -n 8 || fail "Term Discovery is active; wait for it to finish before retrying"

running_services_text="$(compose ps --status running --services)"
running_services=()
if [[ -n "$running_services_text" ]]; then
  mapfile -t running_services <<< "$running_services_text"
fi

services_need_restore=1
restore_services() {
  status=$?
  trap - EXIT
  if [[ "$services_need_restore" == "1" && "${#running_services[@]}" -gt 0 ]]; then
    printf '\nRestoring previously running services: %s\n' "${running_services[*]}" >&2
    if ! compose start "${running_services[@]}" >/dev/null; then
      printf 'ERROR: could not restore the previously running Compose services\n' >&2
      [[ "$status" -ne 0 ]] || status=1
    fi
  fi
  exit "$status"
}
trap restore_services EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

compose stop frontend backend

printf '\nCreating the pre-reset backup...\n'
backup_output="$(compose run --rm --no-deps -T -w /workspace --entrypoint python backend /workspace/scripts/backup.py --output-dir /backups)"
printf '%s\n' "$backup_output"
backup_archive="$(printf '%s\n' "$backup_output" | sed -n 's/^Created \(.*\) (.*/\1/p' | tail -n 1)"
[[ -n "$backup_archive" ]] || fail "backup.py did not report the new archive path"

printf '\nVerifying the backup archive and its SQLite snapshot...\n'
compose run --rm --no-deps -T -w /workspace --entrypoint python backend - "$backup_archive" <<'PY'
from pathlib import Path
import json
import sqlite3
import sys
import tarfile
import tempfile

archive_path = Path(sys.argv[1])
required = {"manifest.json", "knowledge.bundle", "runtime/knowledge.db", "storage.tar.gz"}
with tarfile.open(archive_path, "r:gz") as archive:
    names = {member.name for member in archive.getmembers()}
    missing = required - names
    if missing:
        raise SystemExit("backup archive is missing: {}".format(", ".join(sorted(missing))))
    manifest_file = archive.extractfile("manifest.json")
    manifest = json.load(manifest_file)
    declared = set(manifest.get("contents", []))
    if not required - {"manifest.json"} <= declared:
        raise SystemExit("backup manifest does not list the expected payloads")

    database_member = archive.extractfile("runtime/knowledge.db")
    with tempfile.TemporaryDirectory(prefix="kb-term-reset-backup-") as directory:
        snapshot = Path(directory) / "knowledge.db"
        snapshot.write_bytes(database_member.read())
        connection = sqlite3.connect("file:{}?mode=ro".format(snapshot), uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SystemExit("backup SQLite integrity_check failed")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != 19:
                raise SystemExit("backup SQLite schema is {}; expected 19".format(version))
        finally:
            connection.close()

    storage_member = archive.extractfile("storage.tar.gz")
    with tempfile.TemporaryDirectory(prefix="kb-term-reset-storage-") as directory:
        storage_snapshot = Path(directory) / "storage.tar.gz"
        with storage_snapshot.open("wb") as output:
            while True:
                chunk = storage_member.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        with tarfile.open(storage_snapshot, "r:gz") as storage:
            for member in storage.getmembers():
                if member.isfile():
                    stream = storage.extractfile(member)
                    while stream.read(1024 * 1024):
                        pass

print("Verified backup archive: {}".format(archive_path))
PY

printf '\nClearing Term-only Runtime data in one SQLite transaction...\n'
reset_output="$(compose run --rm --no-deps -T -w /workspace --entrypoint python backend - <<'PY'
import hashlib
import json
import os
import sqlite3

database_path = os.environ["DATABASE_PATH"]
connection = sqlite3.connect(database_path, timeout=30)
connection.execute("PRAGMA busy_timeout = 30000")
connection.execute("PRAGMA foreign_keys = ON")

try:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version != 19:
        raise RuntimeError("Runtime schema changed during reset: {}".format(version))

    existing_tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    required_tables = {
        "term_candidates", "term_candidate_evidence", "term_entity_relations",
        "term_merge_history", "term_discovery_settings", "term_discovery_runs",
        "term_discovery_run_items", "document_term_analysis_state",
        "corpus_analysis_state", "vocabulary_source_statistics",
        "presentation_annotations", "collection_node_index", "rejected_candidates",
        "drafts", "proposals", "term_index", "alias_index", "term_fts",
        "pdf_corpus", "import_jobs", "import_items", "usage_events",
        "document_index", "source_index", "research_works",
        "research_discoveries", "research_work_analyses", "research_candidates",
        "research_search_state", "research_runs", "research_run_requests",
        "research_entity_links", "research_pending_links", "research_profile_state",
        "research_control_events",
    }
    missing_tables = required_tables - existing_tables
    if missing_tables:
        raise RuntimeError("schema 19 is missing expected tables: {}".format(
            ", ".join(sorted(missing_tables))
        ))

    protected_tables = sorted(
        name for name in existing_tables if name.startswith("research_")
    ) + [
        "import_jobs", "import_items", "pdf_corpus", "usage_events",
        "document_index", "source_index",
    ]

    def fingerprint(table):
        quoted = '"{}"'.format(table.replace('"', '""'))
        rows = [
            json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":"), default=str)
            for row in connection.execute("SELECT * FROM {}".format(quoted))
        ]
        rows.sort()
        digest = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
        return {"rows": len(rows), "sha256": digest}

    connection.execute("BEGIN IMMEDIATE")
    preserved_before = {table: fingerprint(table) for table in protected_tables}

    connection.execute("DELETE FROM term_discovery_run_items")
    connection.execute("DELETE FROM term_discovery_runs")
    connection.execute("DELETE FROM term_discovery_settings")
    connection.execute("DELETE FROM term_candidate_evidence")
    connection.execute("DELETE FROM term_candidates")
    connection.execute("DELETE FROM rejected_candidates WHERE candidate_type = 'term'")
    connection.execute("DELETE FROM drafts WHERE entity_type = 'term'")
    connection.execute("DELETE FROM proposals WHERE target_type = 'term'")
    connection.execute("DELETE FROM term_entity_relations")
    connection.execute("DELETE FROM term_merge_history")
    connection.execute("DELETE FROM document_term_analysis_state")
    connection.execute("DELETE FROM corpus_analysis_state")
    connection.execute("DELETE FROM vocabulary_source_statistics")
    connection.execute("DELETE FROM presentation_annotations WHERE entity_type = 'term'")
    connection.execute(
        "DELETE FROM collection_node_index WHERE kind = 'entity' AND entity_type = 'term'"
    )
    connection.commit()

    checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if checkpoint[0] != 0:
        raise RuntimeError("SQLite WAL checkpoint is busy; database remains backed up")
finally:
    connection.close()

print("PRESERVED_STATE_JSON=" + json.dumps(
    preserved_before, ensure_ascii=False, sort_keys=True, separators=(",", ":")
))
PY
)"
printf '%s\n' "$reset_output" | sed '/^PRESERVED_STATE_JSON=/d'
preserved_state="$(printf '%s\n' "$reset_output" | sed -n 's/^PRESERVED_STATE_JSON=//p' | tail -n 1)"
[[ -n "$preserved_state" ]] || fail "Runtime reset did not return preservation checksums"

printf '\nRebuilding disposable indexes from canonical files...\n'
compose run --rm --no-deps -T -w /workspace --entrypoint python backend /workspace/tools/kb.py rebuild --root /workspace --database /workspace/runtime/knowledge.db

printf '\nVerifying reset results and preserved Research/Import/PDF data...\n'
compose run --rm --no-deps -T -w /workspace --entrypoint python backend - "$preserved_state" <<'PY'
import hashlib
import json
import os
import sqlite3
import sys

connection = sqlite3.connect(os.environ["DATABASE_PATH"], timeout=30)
try:
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise SystemExit("Runtime SQLite integrity_check failed after reset")
    if connection.execute("PRAGMA user_version").fetchone()[0] != 19:
        raise SystemExit("Runtime schema changed during reset")

    expected_preserved = json.loads(sys.argv[1])

    def fingerprint(table):
        quoted = '"{}"'.format(table.replace('"', '""'))
        rows = [
            json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":"), default=str)
            for row in connection.execute("SELECT * FROM {}".format(quoted))
        ]
        rows.sort()
        digest = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
        return {"rows": len(rows), "sha256": digest}

    actual_preserved = {table: fingerprint(table) for table in expected_preserved}
    if actual_preserved != expected_preserved:
        raise SystemExit("Research, Imports, PDF Corpus, Documents, or Sources changed")

    checks = {
        "term candidates": ("SELECT COUNT(*) FROM term_candidates", ()),
        "Term Candidate Evidence": ("SELECT COUNT(*) FROM term_candidate_evidence", ()),
        "Term relations": ("SELECT COUNT(*) FROM term_entity_relations", ()),
        "Term merge history": ("SELECT COUNT(*) FROM term_merge_history", ()),
        "Term Discovery settings": ("SELECT COUNT(*) FROM term_discovery_settings", ()),
        "Term Discovery runs": ("SELECT COUNT(*) FROM term_discovery_runs", ()),
        "Term Discovery run items": ("SELECT COUNT(*) FROM term_discovery_run_items", ()),
        "Term Reject Memory": (
            "SELECT COUNT(*) FROM rejected_candidates WHERE candidate_type = 'term'", ()
        ),
        "Term Drafts": ("SELECT COUNT(*) FROM drafts WHERE entity_type = 'term'", ()),
        "Term Proposals": ("SELECT COUNT(*) FROM proposals WHERE target_type = 'term'", ()),
        "Document Term Analysis cache": ("SELECT COUNT(*) FROM document_term_analysis_state", ()),
        "PDF Term Analysis cache": ("SELECT COUNT(*) FROM corpus_analysis_state", ()),
        "PDF vocabulary statistics": ("SELECT COUNT(*) FROM vocabulary_source_statistics", ()),
        "Term presentation annotations": (
            "SELECT COUNT(*) FROM presentation_annotations WHERE entity_type = 'term'", ()
        ),
        "Term Collection nodes": (
            "SELECT COUNT(*) FROM collection_node_index WHERE kind = 'entity' AND entity_type = 'term'", ()
        ),
        "Term index": ("SELECT COUNT(*) FROM term_index", ()),
        "Term aliases": ("SELECT COUNT(*) FROM alias_index", ()),
        "Term full-text index": ("SELECT COUNT(*) FROM term_fts", ()),
    }
    remaining = {
        label: connection.execute(sql, parameters).fetchone()[0]
        for label, (sql, parameters) in checks.items()
    }
    nonzero = {label: count for label, count in remaining.items() if count}
    if nonzero:
        raise SystemExit("Term-only records remain: {}".format(nonzero))

    print("Verified preserved table fingerprints for {} tables.".format(len(actual_preserved)))
    print("Verified {} Term-only record/index counts are zero.".format(len(remaining)))
finally:
    connection.close()
PY

printf '\nTERM TEST DATA RESET: PASS\n'
