#!/usr/bin/env python3
"""Check or synchronize the explicitly selected learning notes."""

import argparse
import json
from pathlib import Path
import os
import sys
from typing import Optional


ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services.ai_client import DeepSeekClient, DeepSeekConfig
from backend.app.services.learning_context_service import LearningContextService
from backend.app.services.ai_gateway import AIGateway


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="learning-context", description="Check and synchronize local learning context."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    sync = commands.add_parser("sync", help="check selected notes and update local context")
    _add_root(sync)
    sync.add_argument("--dry-run", action="store_true", help="show local changes without calling AI or writing files")
    sync.add_argument("--force", action="store_true", help="reanalyze all selected notes (or one with --source-id)")
    sync.add_argument("--source-id", help="limit this run to one selected note; combine with --force to reanalyze it")
    status = commands.add_parser("status", help="show the last local synchronization status")
    _add_root(status)
    args = parser.parse_args(argv)
    root = _resolve_root(args.root)

    if args.command == "status":
        result = LearningContextService(root).get_overview()["status"]
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    gateway = None if args.dry_run else _LazyAIGateway(root)
    service = LearningContextService(root, gateway)
    result = service.sync(
        dry_run=args.dry_run,
        force=args.force,
        source_id=args.source_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["state"] in {"synced", "no_sources", "dry_run"} else 1


def _add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, help="KnowledgeBase repository root")


def _resolve_root(root: Optional[Path]) -> Path:
    configured = root or os.environ.get("KNOWLEDGE_REPO_PATH") or ROOT
    return Path(configured).expanduser().resolve()


class _LazyAIGateway:
    """Load AI configuration only if local diffing finds knowledge to analyze."""

    def __init__(self, repository_root: Path):
        self.repository_root = repository_root
        self.gateway = None

    def run(self, task_name: str, context: dict):
        if self.gateway is None:
            self.gateway = AIGateway(
                DeepSeekClient(DeepSeekConfig.from_environment(self.repository_root))
            )
        return self.gateway.run(task_name, context)


if __name__ == "__main__":
    raise SystemExit(main())
