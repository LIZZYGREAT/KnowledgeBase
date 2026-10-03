#!/usr/bin/env python3
"""Research Agent configuration checks."""

import argparse
from pathlib import Path
import sys
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.services.research_profile_registry import ResearchProfileRegistry


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="research", description="Research Agent commands.")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate Research config and Profile references")
    check.add_argument("--root", type=Path, default=ROOT, help="KnowledgeBase repository root")
    args = parser.parse_args(argv)

    if args.command == "check":
        try:
            registry = ResearchProfileRegistry.load(args.root)
        except (OSError, UnicodeError, ValueError) as error:
            print("ERROR research check: {}".format(error))
            return 1
        print(
            "Research configuration valid: {} Profile(s).".format(
                len(registry.profiles)
            )
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
