"""Measure repeated read-API timings without imposing a pass/fail threshold."""

import argparse
import json
import statistics
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_json(base_url: str, path: str):
    request = Request(base_url.rstrip("/") + path, headers={"Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def measure(base_url: str, path: str, repeats: int) -> list[float]:
    timings = []
    for _ in range(repeats):
        started = time.perf_counter()
        get_json(base_url, path)
        timings.append((time.perf_counter() - started) * 1000)
    return timings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--source-id")
    parser.add_argument("--term-id")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    cases = [
        ("Home summary", "/api/ui/summary"),
        ("Home Discovery state", "/api/terms/discovery"),
        ("Library documents", "/api/documents?limit=1&offset=0"),
        ("Terms list", "/api/terms?limit=1&offset=0"),
        ("Research profiles", "/api/research/profiles"),
    ]
    try:
        if not args.source_id:
            sources = get_json(args.base_url, "/api/sources?limit=1&offset=0")
            args.source_id = sources[0]["id"] if sources else None
        if not args.term_id:
            terms = get_json(args.base_url, "/api/terms?limit=1&offset=0")
            args.term_id = terms[0]["id"] if terms else None
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as error:
        print("Could not select detail samples: {}".format(error))

    if args.source_id:
        cases.append(("Source detail", "/api/sources/{}".format(args.source_id)))
    else:
        print("Source detail: skipped (no Source is available; pass --source-id to select one)")
    if args.term_id:
        cases.append(("Term detail", "/api/terms/{}".format(args.term_id)))
    else:
        print("Term detail: skipped (no Term is available; pass --term-id to select one)")

    failed = False
    for label, path in cases:
        try:
            timings = measure(args.base_url, path, args.repeat)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            failed = True
            print("{}: failed ({})".format(label, error))
            continue
        print(
            "{}: median={:.1f} ms max={:.1f} ms ({} requests)".format(
                label, statistics.median(timings), max(timings), len(timings)
            )
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
