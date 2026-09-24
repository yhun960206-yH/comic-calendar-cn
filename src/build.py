"""Build complete, deterministic city calendars without touching output on input failure."""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urljoin

from .model import InputError, check_transition, cities, events, https_url, read_json
from .site import render_site

ROOT = Path(__file__).resolve().parent.parent


def escape_text(value):
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    """RFC 5545 content lines: 75 UTF-8 octets including the continuation space."""
    parts = []
    current = ""
    length = 0
    for char in line:
        size = len(char.encode("utf-8"))
        if length + size > 75:
            parts.append(current)
            current, length = " ", 1
        current += char
        length += size
    parts.append(current)
    return "\r\n".join(parts)


def calendar(city, city_events, demo):
    name = ("DEMO 演示 · " if demo else "") + city["name"] + "漫展日历"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Comic Calendar//City Feeds//ZH",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:" + escape_text(name)]
    for event in city_events:
        address = event["venue_address"]
        details = ["场馆：" + event["venue_name"], "详细地址：" + address]
        if event.get("guests"):
            details.append("嘉宾：" + "、".join(event["guests"]))
        if event.get("attribution"):
            details.append("数据来源署名：" + event["attribution"])
        details += ["票务：" + (event.get("ticket_url") or "待公布"),
                    "地图：" + (event.get("map_url") or "待核实"),
                    "公告来源：" + event["source_url"]]
        if demo:
            details.insert(0, "DEMO 演示数据，非真实活动")
        stamp = event["updated_at"].replace("-", "").replace(":", "")
        if "start_at" in event:
            start = datetime.fromisoformat(event["start_at"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            end = datetime.fromisoformat(event["end_at"]).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            time_lines = ["DTSTART:" + start, "DTEND:" + end]
        else:
            time_lines = ["DTSTART;VALUE=DATE:" + event["start_date"].replace("-", ""),
                          "DTEND;VALUE=DATE:" + event["end_date"].replace("-", "")]
        lines += ["BEGIN:VEVENT", "UID:" + event["event_id"] + "@comic-calendar.invalid",
                  "DTSTAMP:" + stamp, "LAST-MODIFIED:" + stamp,
                  "SEQUENCE:" + str(event["revision"]), *time_lines,
                  "STATUS:" + event["status"].upper(),
                  "SUMMARY:" + escape_text(("[DEMO] " if demo else "") +
                                            ("已取消 · " if event["status"] == "cancelled" else "") + event["title"]),
                  "LOCATION:" + escape_text(event["venue_name"] + " · " + address),
                  "DESCRIPTION:" + escape_text("\n".join(details)),
                  "URL:" + (event.get("ticket_url") or event["source_url"]), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(fold(line) for line in lines) + "\r\n").encode("utf-8")


def _write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build(*, base_url, output, input_path=None, config_path=None, demo=False):
    https_url(base_url, "base-url", directory=True)
    city_list = cities(config_path or ROOT / "config/cities.json")
    source = Path(input_path or ROOT / ("data/seed_events.json" if demo else "data/events.json")).resolve()
    if source == (ROOT / "data/seed_events.json").resolve() and not demo:
        raise InputError("seed events require --demo")
    items = events(source)
    target = Path(output).absolute()
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise InputError("output must be an ordinary directory or not exist")
    if (target / "events.json").exists():
        prior = read_json(target / "events.json")
        if not isinstance(prior, dict) or not isinstance(prior.get("events"), list) or type(prior.get("demo")) is not bool:
            raise InputError("existing published events.json is malformed")
        if prior["demo"] == demo:
            check_transition(prior["events"], items)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".calendar-build-", dir=target.parent) as tmp:
        staging = Path(tmp) / "next"
        feed_dir = staging / "feeds/cities"
        feed_dir.mkdir(parents=True)
        public_cities = []
        for city in city_list:
            code = city["code"]
            url = urljoin(base_url, "feeds/cities/" + code + ".ics")
            city_events = [event for event in items if event["city_code"] == code]
            (feed_dir / (code + ".ics")).write_bytes(calendar(city, city_events, demo))
            public_cities.append({**city, "feed_url": url, "event_count": len(city_events)})
        _write_json(staging / "events.json", {"demo": demo, "cities": public_cities, "events": items})
        _write_json(staging / "status.json", {"ok": True, "demo": demo, "event_count": len(items),
                                              "last_verified_at": max((item["updated_at"] for item in items), default=None),
                                              "cities": public_cities})
        render_site(staging, public_cities, items, demo)
        # All rendering and writes finish before publication. Roll back the old
        # directory if the second rename fails. Readers may see a brief gap.
        previous = Path(tmp) / "previous"
        had_previous = target.exists()
        if had_previous:
            os.replace(target, previous)
        try:
            os.replace(staging, target)
        except BaseException:
            if had_previous:
                os.replace(previous, target)
            raise
        if had_previous:
            shutil.rmtree(previous)
    return len(items)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Publish complete city ICS feeds and website JSON")
    parser.add_argument("--base-url", required=True, help="HTTPS site root, including trailing /")
    parser.add_argument("--output", default="public", help="output directory (replaced in full)")
    parser.add_argument("--demo", action="store_true", help="explicitly use DEMO seed data")
    parser.add_argument("--input", type=Path, help="override selected events file (for local validation/testing)")
    args = parser.parse_args(argv)
    try:
        count = build(base_url=args.base_url, output=args.output, input_path=args.input, demo=args.demo)
    except (InputError, OSError) as exc:
        print(f"build failed: {exc}", file=sys.stderr)
        return 1
    print(f"published {count} events ({'DEMO' if args.demo else 'real'}) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
