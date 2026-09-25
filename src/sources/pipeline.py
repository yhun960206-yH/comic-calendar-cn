"""FEC publication preparation using the last live Pages data as a checkpoint.

This module does not publish or commit. If source or checkpoint access fails, the
caller must abort its Pages deployment; the already live artifact stays intact.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from ..model import InputError, check_transition, events, https_url
from .bili_channel import (BiliSourceError, count_published, prune_expired,
                           fetch_candidates as bili_candidates)
from .fec import SourceError, fetch_all, merge_prepared, reconcile
from .fec_web import WebSourceError, fetch_candidates

MAX_CHECKPOINT_BYTES = 5_000_000
# 源异常缩水保护：上次有记录时，本次不得低于其一半。
MIN_KEEP_RATIO = 2


def load_published(base_url, *, opener=urlopen, run_id=""):
    https_url(base_url, "base-url", directory=True)
    # A unique query prevents a recently cached artifact from being treated as
    # the current checkpoint on an immediate rerun. Do not follow a redirect
    # to a different host when using an untrusted HTTP client implementation.
    url = urljoin(base_url, "events.json")
    if run_id:
        if not run_id.isdigit():
            raise SourceError("run_id must be a numeric GitHub run identifier")
        url += "?checkpoint_run=" + run_id
    try:
        with opener(Request(url, headers={"Accept": "application/json", "Cache-Control": "no-cache"}), timeout=20) as response:
            if response.geturl().split("?", 1)[0] != url.split("?", 1)[0]:
                raise SourceError("published checkpoint redirected unexpectedly")
            body = response.read(MAX_CHECKPOINT_BYTES + 1)
        if len(body) > MAX_CHECKPOINT_BYTES:
            raise SourceError("published checkpoint exceeded 5 MB")
        payload = json.loads(body)
    except (OSError, ValueError, UnicodeError) as exc:
        raise SourceError(f"cannot read published checkpoint: {exc}") from exc
    if (not isinstance(payload, dict) or payload.get("demo") is not False or
        not isinstance(payload.get("events"), list)):
        raise SourceError("published checkpoint missing or contains demo data")
    return payload["events"]


def _previous(base_url, local_path, *, opener, run_id):
    published = load_published(base_url, opener=opener, run_id=run_id)
    local = events(local_path)
    # Validate the remote event schema and protect local, history-backed edits.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        old_path = Path(directory) / "published.json"
        old_path.write_text(json.dumps({"events": published}, ensure_ascii=False), encoding="utf-8")
        previous = events(old_path)
    by_id = {event["event_id"]: event for event in previous}
    for event in local:
        old = by_id.get(event["event_id"])
        if old is None:
            by_id[event["event_id"]] = event
        elif old != event and event["revision"] > old["revision"]:
            check_transition([old], [event])
            by_id[event["event_id"]] = event
        elif old != event and event["revision"] == old["revision"]:
            raise SourceError(f"local and published revisions disagree for {event['event_id']}")
    return sorted(by_id.values(), key=lambda e: (e["start_date"], e["event_id"]))


def _write_candidate(local_path, output, merged):
    target = Path(output)
    if target.resolve() == Path(local_path).resolve():
        raise SourceError("candidate output must not overwrite the repository input")
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        candidate = Path(directory) / "events.json"
        candidate.write_text(json.dumps({"events": merged}, ensure_ascii=False), encoding="utf-8")
        events(candidate)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(candidate.read_bytes())


def prepare(base_url, key, local_path, output, *, opener=urlopen, source_fetch=fetch_all, run_id=""):
    if not key:
        raise SourceError("FEC_API_KEY is required")
    previous = _previous(base_url, local_path, opener=opener, run_id=run_id)
    rows = source_fetch(key)
    if not isinstance(rows, list):
        raise SourceError("source fetch must return a complete list")
    prior_fec_count = sum(e["event_id"].startswith("fec-") for e in previous)
    if prior_fec_count and not rows:
        raise SourceError("source suddenly returned no events; retain previous site")
    if prior_fec_count > 10 and len(rows) < prior_fec_count // 2:
        raise SourceError("source result count dropped sharply; retain previous site")
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged, quarantine = reconcile(previous, rows, observed_at)
    if rows and not any(event["event_id"].startswith("fec-") for event in merged):
        raise SourceError("source returned rows but none passed quality gates; retain previous site")
    _write_candidate(local_path, output, merged)
    return {"source_rows": len(rows), "eligible_events": len(merged), "quarantined": quarantine,
            "observed_at": observed_at}


def prepare_web(base_url, local_path, output, *, opener=urlopen, web_fetch=fetch_candidates, run_id=""):
    """Refresh from public, licensed HTML without tokens or hidden APIs."""
    previous = _previous(base_url, local_path, opener=opener, run_id=run_id)
    ready, skipped, observed_at = web_fetch()
    merged, conflicts = merge_prepared(previous, ready, observed_at)
    if not ready:
        raise SourceError("no complete public FEC expo records; retain previous site")
    _write_candidate(local_path, output, merged)
    return {"source_rows": len(ready) + len(skipped), "eligible_events": len(merged),
            "quarantined": skipped + conflicts, "observed_at": observed_at}


def prepare_multi(base_url, key, local_path, output, *, use_web, use_bili, opener=urlopen,
                  source_fetch=fetch_all, web_fetch=fetch_candidates,
                  bili_fetch=bili_candidates, run_id=""):
    """从同一检查点依次合并多个来源，只写一次候选文件。

    任一来源失败就整轮不输出，已发布的旧站保持不动。
    """
    previous = _previous(base_url, local_path, opener=opener, run_id=run_id)
    previous, pruned = prune_expired(previous)
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged = previous
    report = {"pruned_expired": pruned, "observed_at": observed_at}

    if key:
        rows = source_fetch(key)
        if not isinstance(rows, list):
            raise SourceError("source fetch must return a complete list")
        prior = sum(e["event_id"].startswith("fec-") for e in merged)
        if prior and not rows:
            raise SourceError("source suddenly returned no events; retain previous site")
        if prior > 10 and len(rows) < prior // MIN_KEEP_RATIO:
            raise SourceError("source result count dropped sharply; retain previous site")
        merged, quarantine = reconcile(merged, rows, observed_at)
        if rows and not any(e["event_id"].startswith("fec-") for e in merged):
            raise SourceError("source returned rows but none passed quality gates; retain previous site")
        report["fec_api"] = {"source_rows": len(rows), "quarantined": quarantine}
    elif use_web:
        ready, skipped, web_observed = web_fetch()
        if not ready:
            raise SourceError("no complete public FEC expo records; retain previous site")
        merged, conflicts = merge_prepared(merged, ready, web_observed)
        report["fec_web"] = {"rows": len(ready) + len(skipped), "quarantined": skipped + conflicts}

    if use_bili:
        prior_bili = count_published(merged)
        ready, skipped, bili_observed = bili_fetch(previous=merged)
        if prior_bili > 20 and len(ready) < prior_bili // MIN_KEEP_RATIO:
            raise SourceError("bilibili result count dropped sharply; retain previous site")
        merged, conflicts = merge_prepared(merged, ready, bili_observed)
        report["bilibili"] = {"eligible": len(ready), "quarantined": skipped + conflicts,
                              "previous": prior_bili}

    _write_candidate(local_path, output, merged)
    report["eligible_events"] = len(merged)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare FEC events from a live Pages checkpoint")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--input", default="data/events.json")
    parser.add_argument("--output", help="candidate input path (required when key is present)")
    parser.add_argument("--check-no-key", action="store_true", help="refuse to erase live API events")
    parser.add_argument("--public-web", action="store_true", help="use public licensed FEC exhibition pages")
    parser.add_argument("--bili", action="store_true", help="also merge the bilibili membership-shop convention channel")
    args = parser.parse_args(argv)
    try:
        if args.public_web or args.bili:
            if not args.output:
                raise SourceError("--output is required")
            report = prepare_multi(args.base_url, os.environ.get("FEC_API_KEY", ""),
                                   args.input, args.output, use_web=args.public_web,
                                   use_bili=args.bili, run_id=os.environ.get("GITHUB_RUN_ID", ""))
            print(json.dumps(report, ensure_ascii=False))
        elif args.check_no_key:
            live = load_published(args.base_url, run_id=os.environ.get("GITHUB_RUN_ID", ""))
            if any(isinstance(e, dict) and str(e.get("event_id", "")).startswith("fec-") for e in live):
                raise SourceError("published FEC events exist, but API key is absent; retain live site")
            print("no published FEC events to preserve")
        else:
            if not args.output:
                raise SourceError("--output is required")
            report = prepare(args.base_url, os.environ.get("FEC_API_KEY", ""), args.input, args.output,
                             run_id=os.environ.get("GITHUB_RUN_ID", ""))
            print(json.dumps(report, ensure_ascii=False))
    except (InputError, SourceError, BiliSourceError, WebSourceError, OSError) as exc:
        print(f"FEC preparation failed; deployment must stop: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
