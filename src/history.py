"""Check the current event ledger against every committed ancestor on the deploy branch.

A Pages runner starts fresh: the local public/ directory is not durable state.
Git history on the protected default branch is the publication ledger.
"""
import subprocess
import sys

from .model import InputError, check_transition, events


def main():
    try:
        current = events("data/events.json")
        commits = subprocess.check_output(
            ["git", "log", "--format=%H", "HEAD", "--", "data/events.json"], text=True
        ).splitlines()
        for commit in commits:
            payload = subprocess.check_output(
                ["git", "show", f"{commit}:data/events.json"], text=True
            )
            # Validate historical input via the same model without writing into the repo.
            from tempfile import TemporaryDirectory
            from pathlib import Path
            with TemporaryDirectory() as directory:
                path = Path(directory) / "events.json"
                path.write_text(payload, encoding="utf-8")
                check_transition(events(path), current)
    except (InputError, subprocess.CalledProcessError, OSError) as exc:
        print(f"history validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"history valid: {len(commits)} prior committed versions checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
