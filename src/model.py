"""Strict input contract shared by the validator and publisher."""

import json
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


CITY_CODES = {"110100": "北京", "310100": "上海"}
REQUIRED = {"event_id", "revision", "status", "city_code", "title", "start_date",
            "end_date", "updated_at", "venue_name", "venue_address", "source_url"}
OPTIONAL = {"guests", "ticket_url", "map_url", "start_at", "end_at"}
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TIME_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
URI_PATTERN = re.compile(r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+\Z")
BAD_PERCENT = re.compile(r"%(?![0-9a-fA-F]{2})")


class InputError(ValueError):
    """Input must not replace any previously published output."""


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise InputError(f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"cannot read JSON {path}: {exc}") from exc


def cities(path):
    data = read_json(path)
    expected = [{"code": code, "name": name} for code, name in CITY_CODES.items()]
    if data != {"cities": expected}:
        raise InputError("cities.json must list exactly Beijing 110100 and Shanghai 310100")
    return expected


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label} must be nonempty text")
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise InputError(f"{label} contains a control character")
    return value


def https_url(value, label, *, directory=False):
    _text(value, label)
    if not value.isascii() or not URI_PATTERN.fullmatch(value) or BAD_PERCENT.search(value):
        raise InputError(f"{label} must be a valid ASCII HTTPS URL (percent-encode non-ASCII)")
    try:
        parts = urlsplit(value)
        # Accessing hostname/port also checks malformed IPv6 and invalid ports.
        host, port = parts.hostname, parts.port
    except ValueError as exc:
        raise InputError(f"{label} is invalid: {exc}") from exc
    if parts.scheme != "https" or not host or parts.username or parts.password or port == 0 or "\\" in value:
        raise InputError(f"{label} must be an HTTPS URL without credentials")
    if directory and (not value.endswith("/") or parts.query or parts.fragment
                      or any(segment in (".", "..") for segment in parts.path.split("/"))):
        raise InputError(f"{label} must end in / and have no query, fragment or dot segments")
    return value


def events(path):
    data = read_json(path)
    if not isinstance(data, dict) or set(data) != {"events"} or not isinstance(data["events"], list):
        raise InputError("events file must be an object containing only an events array")
    seen = set()
    result = []
    for index, event in enumerate(data["events"]):
        label = f"events[{index}]"
        if not isinstance(event, dict) or not REQUIRED <= set(event) or set(event) - REQUIRED - OPTIONAL:
            raise InputError(f"{label} must have required fields and only documented optional fields")
        event_id = event["event_id"]
        if not isinstance(event_id, str) or not ID_PATTERN.fullmatch(event_id):
            raise InputError(f"{label}.event_id must match [a-z0-9][a-z0-9._-]*")
        if event_id in seen:
            raise InputError(f"duplicate event_id: {event_id}")
        seen.add(event_id)
        if not isinstance(event["city_code"], str) or event["city_code"] not in CITY_CODES:
            raise InputError(f"{label}.city_code must be 110100 or 310100")
        if event["status"] not in ("confirmed", "cancelled"):
            raise InputError(f"{label}.status must be confirmed or cancelled")
        if type(event["revision"]) is not int or event["revision"] < 0:
            raise InputError(f"{label}.revision must be a nonnegative integer")
        for field in ("title", "venue_name", "venue_address"):
            _text(event[field], f"{label}.{field}")
        https_url(event["source_url"], f"{label}.source_url")
        for field in ("ticket_url", "map_url"):
            if field in event and event[field] is not None:
                https_url(event[field], f"{label}.{field}")
        if "guests" in event:
            if not isinstance(event["guests"], list):
                raise InputError(f"{label}.guests must be an array")
            for guest in event["guests"]:
                _text(guest, f"{label}.guests[]")
        for field in ("start_date", "end_date"):
            value = event[field]
            if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
                raise InputError(f"{label}.{field} must be YYYY-MM-DD")
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise InputError(f"{label}.{field} is invalid") from exc
        if event["end_date"] <= event["start_date"]:
            raise InputError(f"{label}.end_date must be after start_date (exclusive)")
        if ("start_at" in event) != ("end_at" in event):
            raise InputError(f"{label} must supply both start_at and end_at")
        if "start_at" in event:
            times = []
            for field in ("start_at", "end_at"):
                value = event[field]
                if (not isinstance(value, str) or
                    not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00", value)):
                    raise InputError(f"{label}.{field} must be Asia/Shanghai ISO time +08:00")
                try:
                    times.append(datetime.fromisoformat(value))
                except ValueError as exc:
                    raise InputError(f"{label}.{field} is invalid") from exc
            if (times[0] >= times[1] or times[0].date().isoformat() != event["start_date"] or
                not (event["start_date"] <= times[1].date().isoformat() < event["end_date"])):
                raise InputError(f"{label} timed range must match inclusive event dates")
        timestamp = event["updated_at"]
        if not isinstance(timestamp, str) or not TIME_PATTERN.fullmatch(timestamp):
            raise InputError(f"{label}.updated_at must be UTC YYYY-MM-DDTHH:MM:SSZ")
        try:
            datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise InputError(f"{label}.updated_at is invalid") from exc
        result.append(event)
    return sorted(result, key=lambda e: (e["start_date"], e["event_id"]))


def check_transition(previous, current):
    """Reject silent removal, city migration and version rollback of published IDs."""
    old = {event["event_id"]: event for event in previous}
    new = {event["event_id"]: event for event in current}
    for event_id, before in old.items():
        after = new.get(event_id)
        if after is None:
            raise InputError(f"published event {event_id} cannot be removed; retain a cancelled record")
        if after["city_code"] != before["city_code"]:
            raise InputError(f"published event {event_id} cannot move cities; cancel in original city")
        if before["status"] == "cancelled" and after["status"] != "cancelled":
            raise InputError(f"published cancellation {event_id} cannot be reversed")
        if after["revision"] < before["revision"]:
            raise InputError(f"published event {event_id} revision decreased")
        if after != before:
            if after["revision"] <= before["revision"]:
                raise InputError(f"published event {event_id} changed without revision increase")
            if after["updated_at"] <= before["updated_at"]:
                raise InputError(f"published event {event_id} changed without newer updated_at")
