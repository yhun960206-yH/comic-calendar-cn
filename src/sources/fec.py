"""Opt-in FEC (兽展日历) open-API candidate importer.

Requires an API key from the provider. Does NOT publish, edit data/events.json,
or assert nationwide coverage. Incomplete/ambiguous records are quarantined.
FEC data is licensed CC BY-SA 4.0; consumers must preserve attribution.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..model import CITY_CODES, InputError, check_transition, events, https_url

API = "https://api.furrycons.cn/open/event/"
SHANGHAI = timezone(timedelta(hours=8))
MAX_PAGES = 20
PAGE_SIZE = 50


class SourceError(RuntimeError):
    pass


def fetch_page(key, page, *, opener=urlopen):
    if not key or not key.strip():
        raise SourceError("FEC_API_KEY is required; obtain one from furrycons.cn/workbench")
    url = API + "?" + urlencode({"current": page, "pageSize": PAGE_SIZE})
    request = Request(url, headers={"Authorization": key, "Accept": "application/json",
                                    "User-Agent": "comic-calendar-cn/1.0 (licensed open API)"})
    try:
        with opener(request, timeout=20) as response:
            payload = json.load(response)
    except (OSError, ValueError) as exc:
        raise SourceError(f"FEC page {page} failed: {exc}") from exc
    if not isinstance(payload, dict) or type(payload.get("total")) is not int or not isinstance(payload.get("data"), list):
        raise SourceError(f"FEC page {page} has unexpected schema; do not publish")
    return payload


def fetch_all(key, *, opener=urlopen):
    first = fetch_page(key, 1, opener=opener)
    total = first["total"]
    if total < 0 or total > MAX_PAGES * PAGE_SIZE:
        raise SourceError("FEC result size exceeds configured safety limit")
    rows = list(first["data"])
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    for page in range(2, pages + 1):
        rows.extend(fetch_page(key, page, opener=opener)["data"])
    if len(rows) < total or (total and not rows):
        raise SourceError("FEC pagination returned fewer events than announced")
    return rows


def resolve_city(region):
    if not isinstance(region, str) or not region.strip():
        return None
    text = region.strip()
    matches = [code for code, name in CITY_CODES.items()
               if text == name or text == name.rstrip("市")]
    return matches[0] if len(matches) == 1 else None


def _local_time(value):
    if not isinstance(value, str):
        raise ValueError("missing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone missing")
    return parsed.astimezone(SHANGHAI)


def normalize(row, observed_at):
    """Return one complete candidate or a reason to quarantine; never invent a venue."""
    if not isinstance(row, dict):
        return None, "not an object"
    city = resolve_city(row.get("region"))
    if city is None:
        return None, "ambiguous or unsupported region"
    address = row.get("address")
    if (not isinstance(address, str) or not address.strip() or
        address.strip() == row.get("region") or len(address.strip()) < 6):
        return None, "venue/address not announced or too vague"
    name = row.get("name")
    uid = row.get("id")
    if not isinstance(uid, str) or not isinstance(name, str) or not name.strip():
        return None, "missing event ID/name"
    try:
        start, end = _local_time(row.get("startDate")), _local_time(row.get("endDate"))
        if end <= start:
            raise ValueError("end is not after start")
        url = https_url(row.get("url"), "FEC source URL")
        if not url.startswith("https://www.furrycons.cn/"):
            raise ValueError("source URL must be an official furrycons.cn event")
        # Guard against malformed source IDs before they reach the stable feed UID.
        import uuid
        event_id = "fec-" + uuid.UUID(uid).hex
    except (ValueError, TypeError, InputError) as exc:
        return None, f"invalid event dates, ID or source URL: {exc}"
    status = {"scheduled": "confirmed", "cancelled": "cancelled"}.get(row.get("status"))
    if status is None:
        return None, "unconfirmed or unknown status"
    return {"event_id": event_id, "revision": 0, "status": status, "city_code": city,
            "title": name.strip(), "start_date": start.date().isoformat(),
            "end_date": (end.date() + timedelta(days=1)).isoformat(),
            "start_at": start.isoformat(timespec="seconds"), "end_at": end.isoformat(timespec="seconds"),
            "updated_at": observed_at, "venue_name": address.strip(),
            "venue_address": address.strip(), "source_url": url,
            "attribution": "FEC·兽展日历 (CC BY-SA 4.0): https://creativecommons.org/licenses/by-sa/4.0/"}, None


def reconcile(previous, candidates, observed_at):
    """Retain missing entries; update revisions only when source fields change."""
    by_id = {event["event_id"]: dict(event) for event in previous}
    quarantined = []
    for row in candidates:
        candidate, reason = normalize(row, observed_at)
        if reason:
            quarantined.append({"source_id": row.get("id") if isinstance(row, dict) else None, "reason": reason})
            continue
        old = by_id.get(candidate["event_id"])
        if old:
            if old["city_code"] != candidate["city_code"] or old["status"] == "cancelled" and candidate["status"] != "cancelled":
                quarantined.append({"source_id": row["id"], "reason": "city migration or cancellation reversal"})
                continue
            relevant = set(candidate) - {"revision", "updated_at"}
            if all(old.get(key) == candidate[key] for key in relevant):
                continue
            candidate["revision"] = old["revision"] + 1
            if observed_at <= old["updated_at"]:
                raise SourceError("observed_at must increase for changed events")
        by_id[candidate["event_id"]] = candidate
    merged = sorted(by_id.values(), key=lambda e: (e["start_date"], e["event_id"]))
    check_transition(previous, merged)
    return merged, quarantined


def main(argv=None):
    parser = argparse.ArgumentParser(description="FEC authorized API dry-run (never publishes)")
    parser.add_argument("--input", type=Path, default=Path("data/events.json"))
    parser.add_argument("--output", type=Path, required=True, help="candidate JSON, not the live events file")
    args = parser.parse_args(argv)
    try:
        key = os.environ.get("FEC_API_KEY", "")
        if not key:
            raise SourceError("FEC_API_KEY missing; apply for an API key at furrycons.cn")
        previous = events(args.input)
        rows = fetch_all(key)
        observed = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        merged, quarantined = reconcile(previous, rows, observed)
        if args.output.resolve() == args.input.resolve():
            raise SourceError("refusing to overwrite the published input")
        result = {"events": merged, "quarantined": quarantined,
                  "source": "FEC·兽展日历 / CC BY-SA 4.0", "observed_at": observed}
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"candidates: {len(merged)}; quarantined: {len(quarantined)}")
    except (SourceError, InputError, OSError) as exc:
        print(f"FEC dry-run failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
