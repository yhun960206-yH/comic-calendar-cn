"""Offline source-data validator; does not publish or mutate files."""

import argparse
import sys
from pathlib import Path

from .model import InputError, cities, events

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate source events and city configuration")
    parser.add_argument("--input", type=Path, default=ROOT / "data/events.json")
    parser.add_argument("--cities", type=Path, default=ROOT / "config/cities.json")
    args = parser.parse_args(argv)
    try:
        cities(args.cities)
        count = len(events(args.input))
    except InputError as exc:
        print(f"invalid: {exc}", file=sys.stderr)
        return 1
    print(f"valid: {count} events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
