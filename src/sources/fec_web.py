"""Read FEC's public, CC BY-SA 4.0 event pages (no account or cookie).

Only schema.org Event records linked as 综合性展会 on the public home page
are candidates. No images or text descriptions are copied. A missing field is
quarantined rather than guessed. The homepage is not a complete catalog.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from ..model import https_url
from .fec import resolve_city

HOME = "https://www.furrycons.cn/"
SHANGHAI = timezone(timedelta(hours=8))
MAX_BYTES = 2_000_000
MAX_EVENTS = 40
LINK = re.compile(r"/[a-zA-Z0-9-]+/[a-zA-Z0-9-]+\Z")
ATTRIBUTION = "FEC·兽展日历 (CC BY-SA 4.0): https://creativecommons.org/licenses/by-sa/4.0/"


class WebSourceError(RuntimeError):
    pass


class PublicHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = []
        self.event_scripts = []
        self._href = None
        self._depth = 0
        self._text = []
        self._jsonld = False
        self._script = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self._jsonld = True
            self._script = []
        if tag == "a" and self._href is None:
            self._href = attrs.get("href")
            self._depth = 1
            self._text = []
        elif self._href is not None:
            self._depth += 1

    def handle_data(self, data):
        if self._jsonld:
            self._script.append(data)
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._jsonld:
            self.event_scripts.append("".join(self._script))
            self._jsonld = False
        if self._href is not None:
            self._depth -= 1
            if self._depth <= 0:
                self.anchors.append((self._href, " ".join("".join(self._text).split())))
                self._href = None


def fetch_html(url, *, opener=urlopen):
    if not (url == HOME or url.startswith(HOME) and LINK.fullmatch(url[len(HOME)-1:])):
        raise WebSourceError("only public FEC event pages are allowed")
    try:
        with opener(Request(url, headers={"User-Agent": "comic-calendar-cn/1.0 (CC BY-SA data)",
                                         "Accept": "text/html"}), timeout=20) as response:
            if response.geturl() != url:
                raise WebSourceError("unexpected redirect from the FEC public page")
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise WebSourceError("FEC page exceeds size limit")
        parser = PublicHTML()
        parser.feed(body.decode("utf-8"))
        return parser
    except (OSError, UnicodeError, ValueError) as exc:
        raise WebSourceError(f"FEC page unavailable: {exc}") from exc


def event_links(home):
    links = sorted({urljoin(HOME, href) for href, text in home.anchors
                    if isinstance(href, str) and LINK.fullmatch(href) and "综合性展会" in text})
    if not links or len(links) > MAX_EVENTS:
        raise WebSourceError("FEC homepage has zero or too many comprehensive expo links")
    return links


def _local_date(value):
    if not isinstance(value, str):
        raise ValueError("missing date")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("date has no timezone")
    return dt.astimezone(SHANGHAI).date()


def normalize_event(page, url, observed_at):
    """Return a validated candidate or one quarantine reason."""
    try:
        objects = [json.loads(raw) for raw in page.event_scripts]
        matches = [obj for obj in objects if isinstance(obj, dict) and obj.get("@type") == "Event"]
        if len(matches) != 1:
            raise ValueError("expected exactly one structured Event")
        data = matches[0]
        if data.get("eventStatus") not in ("https://schema.org/EventScheduled", "https://schema.org/EventCancelled"):
            raise ValueError("event status is unconfirmed")
        place = data.get("location")
        if not isinstance(place, dict) or not isinstance(place.get("address"), dict):
            raise ValueError("no structured venue")
        address = place["address"]
        if address.get("addressCountry") != "CN":
            raise ValueError("outside supported Chinese regions")
        city = resolve_city(address.get("addressLocality"))
        venue = place.get("name")
        street = address.get("streetAddress")
        name = data.get("name")
        if not city or not all(isinstance(v, str) and v.strip() for v in (venue, street, name)):
            raise ValueError("city, venue, address or title missing")
        start, end = _local_date(data.get("startDate")), _local_date(data.get("endDate"))
        if end < start:
            raise ValueError("end date before start")
        https_url(url, "FEC event source")
        event_id = "fec-web-" + hashlib.sha256(url.encode("ascii")).hexdigest()[:20]
        return {"event_id": event_id, "revision": 0,
                "status": "cancelled" if data["eventStatus"].endswith("EventCancelled") else "confirmed",
                "city_code": city, "title": "兽展 · " + name.strip(), "start_date": start.isoformat(),
                "end_date": (end + timedelta(days=1)).isoformat(),
                "updated_at": observed_at, "venue_name": venue.strip(), "venue_address": street.strip(),
                "source_url": url, "attribution": ATTRIBUTION}, None
    except (ValueError, TypeError, KeyError) as exc:
        return None, str(exc)


def fetch_candidates(*, opener=urlopen, pause=0.4):
    homepage = fetch_html(HOME, opener=opener)
    links = event_links(homepage)
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    accepted = []
    quarantined = []
    for url in links:
        if pause:
            time.sleep(pause)
        try:
            candidate, reason = normalize_event(fetch_html(url, opener=opener), url, observed_at)
        except WebSourceError as exc:
            # A partial listing is not a publishable replacement.
            raise WebSourceError(f"FEC event page failed; retain previous site: {exc}") from exc
        if candidate:
            accepted.append(candidate)
        else:
            quarantined.append({"source_url": url, "reason": reason})
    if not accepted:
        raise WebSourceError("no complete FEC exhibition records; retain previous site")
    return accepted, quarantined, observed_at
