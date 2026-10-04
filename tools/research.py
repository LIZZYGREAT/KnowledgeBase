#!/usr/bin/env python3
"""Validate, inspect, and run the KnowledgeBase Research Agent."""

import argparse
from pathlib import Path
import os
import sys
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.db.connection import connect_database
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.research_candidate_repository import (
    ResearchCandidateRepository,
)
from backend.app.repositories.research_run_repository import (
    ResearchProfileStateRepository,
    ResearchRunRepository,
)
from backend.app.repositories.research_run_request_repository import (
    ResearchRunRequestRepository,
)
from backend.app.bootstrap import (
    build_research_components,
    load_research_configuration,
)
from backend.app.services.canonical_target_resolver import CanonicalTargetResolver
from backend.app.services.draft_service import DraftService
from backend.app.services.git_manager import GitManager
from backend.app.services.research_conversion_service import ResearchConversionService
from backend.app.services.research_profile_registry import ResearchProfileRegistry


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="research", description="Operate the KnowledgeBase Research Agent."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser(
        "check", help="validate Research config and Profile references without network calls"
    )
    check.add_argument("--root", type=Path, help="KnowledgeBase repository root")

    profiles = commands.add_parser("profiles", help="list configured Research Profiles")
    _add_root_argument(profiles)

    status = commands.add_parser("status", help="show Research runtime status")
    _add_runtime_arguments(status)

    tick = commands.add_parser("tick", help="process one queued or due Research Run")
    _add_runtime_arguments(tick)

    run = commands.add_parser(
        "run", help="diagnostically run one Research Profile directly"
    )
    _add_runtime_arguments(run)
    run.add_argument("--profile", required=True, help="Research Profile id")
    run.add_argument(
        "--manual",
        action="store_true",
        help="run immediately as a manual diagnostic, bypassing the scheduled due check",
    )

    reconcile = commands.add_parser(
        "reconcile", help="recover completed Research conversions after a publish"
    )
    _add_runtime_arguments(reconcile)

    args = parser.parse_args(argv)
    root = _resolve_root(getattr(args, "root", None))

    if args.command == "check":
        return _check(root)
    if args.command == "profiles":
        return _profiles(root)
    if args.command == "status":
        return _status(root, _resolve_database(root, args.database))
    if args.command == "reconcile":
        return _reconcile(root, _resolve_database(root, args.database))
    if args.command in {"tick", "run"}:
        return _execute(root, _resolve_database(root, args.database), args)
    return 2


def _add_root_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, help="KnowledgeBase repository root")


def _add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    _add_root_argument(parser)
    parser.add_argument(
        "--database", type=Path, help="Runtime SQLite path (defaults to <root>/runtime/knowledge.db)"
    )


def _resolve_root(root: Optional[Path]) -> Path:
    configured = root or os.environ.get("KNOWLEDGE_REPO_PATH") or ROOT
    return Path(configured).expanduser().resolve()


def _resolve_database(root: Path, configured: Optional[Path]) -> Path:
    value = configured or os.environ.get("DATABASE_PATH")
    database = Path(value).expanduser() if value else root / "runtime" / "knowledge.db"
    return (root / database).resolve() if not database.is_absolute() else database.resolve()


def _check(root: Path) -> int:
    try:
        registry, _ = load_research_configuration(root)
    except Exception as error:
        print("ERROR research check: {}".format(error))
        return 1
    print(
        "Research configuration valid: {} Profile(s); AI configuration valid.".format(
            len(registry.profiles)
        )
    )
    return 0


def _profiles(root: Path) -> int:
    try:
        registry = ResearchProfileRegistry.load(root)
    except Exception as error:
        print("ERROR research profiles: {}".format(error))
        return 1
    if not registry.profiles:
        print("No Research Profiles configured.")
        return 0
    for profile in registry.profiles:
        enabled = "enabled" if profile.enabled else "disabled"
        lenses = ", ".join(
            "{}{}".format(lens.id, "" if lens.enabled else " (off)")
            for lens in profile.lenses
        )
        print(
            "{} · {} · {} · schedule {} · discovery {} · lenses {}".format(
                profile.id,
                profile.title,
                enabled,
                profile.schedule.mode,
                ",".join(profile.providers.discovery),
                lenses,
            )
        )
    return 0


def _status(root: Path, database_path: Path) -> int:
    connection = None
    try:
        registry = ResearchProfileRegistry.load(root)
        connection = connect_database(database_path)
        candidates = ResearchCandidateRepository(connection)
        profile_states = ResearchProfileStateRepository(connection)
        runs = ResearchRunRepository(connection)
        requests = ResearchRunRequestRepository(connection)
        print("Research Runtime Status")
        for profile in registry.profiles:
            state = profile_states.get(profile.id)
            latest = runs.list_for_profile(profile.id, limit=1)
            inbox_count = candidates.count_new(profile.id)
            pending, claimed = requests.count_pending_and_claimed(profile.id)
            last_success = (
                state.last_successful_scheduled_run_at
                if state is not None and state.last_successful_scheduled_run_at
                else "never"
            )
            paused = (
                state.paused_until
                if state is not None and state.paused_until
                else "no"
            )
            latest_run = (
                "{} ({})".format(latest[0].status, latest[0].started_at)
                if latest
                else "none"
            )
            print(
                "{} · inbox {}/{} · paused {} · last success {} · latest run {} · "
                "manual requests pending/claimed {}/{}".format(
                    profile.id,
                    inbox_count,
                    profile.inbox.max_new_candidates,
                    paused,
                    last_success,
                    latest_run,
                    pending,
                    claimed,
                )
            )
    except Exception as error:
        print("ERROR research status: {}".format(error))
        return 1
    finally:
        if connection is not None:
            connection.close()
    return 0


def _execute(root: Path, database_path: Path, args) -> int:
    connection = None
    try:
        connection = connect_database(database_path)
        service = build_research_components(root, connection).research_service
        if args.command == "tick":
            run = service.tick()
            if run is None:
                print("No queued manual request or due scheduled Profile.")
                return 0
            label = "Research tick"
        else:
            trigger = "manual" if args.manual else "scheduled"
            run = service.run_profile(args.profile, trigger=trigger)
            if run is None:
                print("Profile '{}' is not due for a scheduled run.".format(args.profile))
                return 0
            label = "Research diagnostic run"
        _print_run(label, run)
        return 1 if run.status in {"failed", "interrupted"} else 0
    except Exception as error:
        print("ERROR research {}: {}".format(args.command, error))
        return 1
    finally:
        if connection is not None:
            connection.close()


def _reconcile(root: Path, database_path: Path) -> int:
    connection = None
    try:
        connection = connect_database(database_path)
        converter = ResearchConversionService(
            root,
            connection,
            DraftService(DraftRepository(connection)),
            GitManager(root),
            CanonicalTargetResolver(root, connection),
        )
        result = converter.reconcile_pending_links()
        print(
            "Research conversion reconcile: {} finalized, {} stale removed, "
            "{} pending.".format(
                result["finalized"], result["stale"], result["pending"]
            )
        )
        for warning in result["warnings"]:
            print("WARNING {}".format(warning))
        return 1 if result["warnings"] else 0
    except Exception as error:
        print("ERROR research reconcile: {}".format(error))
        return 1
    finally:
        if connection is not None:
            connection.close()


def _print_run(label: str, run) -> None:
    print(
        "{} {} · Profile {} · {} · {}".format(
            label, run.id, run.profile_id, run.trigger, run.status
        )
    )
    print(
        "fetched {} · new Works {} · duplicates {} · filtered {} · analyzed {} · "
        "Candidates {}".format(
            run.fetched_count,
            run.new_work_count,
            run.duplicate_count,
            run.deterministic_filtered_count,
            run.analyzed_count,
            run.surfaced_count,
        )
    )
    if run.error_summary:
        print("Errors: {}".format(run.error_summary))


if __name__ == "__main__":
    raise SystemExit(main())
