import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import build, history
from src.model import AREA_TO_CITY, CITY_CODES, InputError, events


BASE = "https://example.github.io/comic-calendar/"


def sample(**changes):
    item = {
        "event_id": "beijing-001", "revision": 0, "status": "confirmed",
        "city_code": "110100", "title": "漫展,北京;\\欢迎", "start_date": "2030-05-01",
        "end_date": "2030-05-03", "updated_at": "2029-12-01T00:00:00Z",
        "venue_name": "演示展馆", "venue_address": "北京路 1 号，展厅",
        "ticket_url": "https://example.com/ticket", "map_url": "https://example.com/map",
        "source_url": "https://example.com/announcement",
        "guests": ["嘉宾甲"]
    }
    item.update(changes)
    return item


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.input = self.dir / "events.json"
        self.output = self.dir / "public"

    def write_events(self, items):
        self.input.write_text(json.dumps({"events": items}, ensure_ascii=False), encoding="utf-8")

    def publish(self, demo=False):
        return build.build(base_url=BASE, output=self.output, input_path=self.input, demo=demo)

    def feed(self, code="110100"):
        return (self.output / f"feeds/cities/{code}.ics").read_bytes()

    def test_empty_publishes_both_complete_feeds_and_subpath_urls(self):
        self.write_events([])
        self.assertEqual(self.publish(), 0)
        for code in ("110100", "310100"):
            content = self.feed(code)
            self.assertTrue(content.startswith(b"BEGIN:VCALENDAR\r\n"))
            self.assertTrue(content.endswith(b"END:VCALENDAR\r\n"))
            self.assertNotIn(b"BEGIN:VEVENT", content)
            self.assertNotIn(b"\n", content.replace(b"\r\n", b""))
        payload = json.loads((self.output / "events.json").read_text())
        self.assertFalse(payload["demo"])
        self.assertEqual(payload["events"], [])
        self.assertEqual(next(c for c in payload["cities"] if c["code"] == "310100")["feed_url"], BASE + "feeds/cities/310100.ics")
        self.assertGreater(len(payload["cities"]), 350)
        self.assertEqual(json.loads((self.output / "status.json").read_text())["event_count"], 0)
        home = (self.output / "index.html").read_text(encoding="utf-8")
        self.assertIn("暂无已收录活动", home)
        self.assertIn("收录来源有限，不能保证普通漫展或其他活动被完整收录", home)
        self.assertIn('id="city-directory"', home)
        self.assertIn('id="how-to-subscribe"', home)
        self.assertIn('support.google.com/calendar/answer/37100', home)
        self.assertIn('support.apple.com/en-us/102301', home)
        self.assertIn('support.microsoft.com/en-us/outlook/', home)
        self.assertIn('不是购票或活动报名', home)
        self.assertIn("目前收录 0 场活动，分布在 0 / 372 个城市", home)
        self.assertIn(BASE + "feeds/cities/110100.ics", home)
        self.assertIn(BASE + "feeds/cities/310100.ics", home)
        self.assertFalse(list((self.output / "events").glob("*.html")))

    def test_populated_city_is_visible_before_empty_cities(self):
        self.write_events([sample(city_code="310100")])
        self.publish()
        home = (self.output / "index.html").read_text(encoding="utf-8")
        self.assertIn("目前收录 1 场活动，分布在 1 / 372 个城市", home)
        self.assertLess(home.index('data-city="310100"'), home.index('data-city="110100"'))
        self.assertIn('data-city="310100" data-count="1"', home)
        self.assertIn('data-city="110100" data-count="0"', home)
        script = (self.output / "assets/site.js").read_text(encoding="utf-8")
        self.assertIn('Number(link.dataset.count) > 0', script)

    def test_change_and_cancellation_keep_uid_and_increment_sequence(self):
        self.write_events([sample()])
        self.publish()
        first = self.feed()
        self.assertIn(b"UID:beijing-001@comic-calendar.invalid\r\n", first)
        self.assertIn(b"DTEND;VALUE=DATE:20300503\r\n", first)
        self.write_events([sample(revision=1, status="cancelled", start_date="2030-05-04",
                                  end_date="2030-05-05", updated_at="2029-12-02T01:02:03Z")])
        self.publish()
        second = self.feed()
        self.assertIn(b"UID:beijing-001@comic-calendar.invalid\r\n", second)
        self.assertIn(b"SEQUENCE:1\r\n", second)
        self.assertIn(b"STATUS:CANCELLED\r\n", second)
        self.assertIn(b"DTSTART;VALUE=DATE:20300504\r\n", second)
        self.assertIn(b"DTSTAMP:20291202T010203Z\r\n", second)
        self.assertNotIn(b"STATUS:CONFIRMED", second)
        self.assertEqual(self.feed("310100").count(b"BEGIN:VEVENT"), 0)

    def test_folding_escaping_and_utf8_octets(self):
        self.write_events([sample(title="漫" * 60 + ",;\\")])
        self.publish()
        content = self.feed()
        self.assertIn("漫".encode(), content)
        self.assertIn(b"\r\n ", content)
        for line in content.split(b"\r\n"):
            self.assertLessEqual(len(line), 75)
        unfolded = content.replace(b"\r\n ", b"")
        self.assertIn("SUMMARY:".encode() + ("漫" * 60).encode() + b"\\,\\;\\\\", unfolded)
        self.assertIn("DESCRIPTION:".encode() + "场馆：".encode(), unfolded)
        self.assertIn("公告来源：https://example.com/announcement".encode(), unfolded)

    def test_invalid_event_and_failed_publish_leave_old_output_unchanged(self):
        self.write_events([sample()])
        self.publish()
        before = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob("*") if p.is_file()}
        for changes in ({"ticket_url": "http://example.com"}, {"source_url": "javascript:alert(1)"},
                        {"end_date": "2030-05-01"},
                        {"status": "pending"}, {"revision": -1}, {"city_code": []},
                        {"title": "bad\r\nINJECT"}):
            self.write_events([sample(**changes)])
            with self.subTest(changes=changes), self.assertRaises(InputError):
                self.publish()
            self.assertEqual(before, {str(p.relative_to(self.output)): p.read_bytes()
                                      for p in self.output.rglob("*") if p.is_file()})
        self.write_events([sample()])
        with patch.object(build, "calendar", side_effect=OSError("simulated render failure")):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(before, {str(p.relative_to(self.output)): p.read_bytes()
                                  for p in self.output.rglob("*") if p.is_file()})
        original_replace = build.os.replace
        calls = 0

        def fail_second_rename(src, dst):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated publish failure")
            return original_replace(src, dst)

        with patch.object(build.os, "replace", side_effect=fail_second_rename):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual(before, {str(p.relative_to(self.output)): p.read_bytes()
                                  for p in self.output.rglob("*") if p.is_file()})

    def test_demo_is_opt_in_and_marked_in_all_products(self):
        self.write_events([sample()])
        self.publish(demo=True)
        self.assertIn(b"[DEMO]", self.feed())
        self.assertIn("DEMO 演示", self.feed().decode("utf-8"))
        self.assertTrue(json.loads((self.output / "events.json").read_text())["demo"])
        self.assertTrue(json.loads((self.output / "status.json").read_text())["demo"])
        self.assertIn("DEMO 演示模式", (self.output / "index.html").read_text())
        self.assertIn("DEMO 演示模式", (self.output / "events/beijing-001.html").read_text())

    def test_detail_escapes_input_and_displays_verified_fields(self):
        self.write_events([sample(title='<img src=x onerror="alert(1)">',
                                  venue_name='<script>alert(1)</script>',
                                  guests=['<em>嘉宾</em>'])])
        self.publish()
        home = (self.output / "index.html").read_text(encoding="utf-8")
        page = (self.output / "events/beijing-001.html").read_text(encoding="utf-8")
        self.assertIn('events/beijing-001.html', home)
        for output in (home, page):
            self.assertIn('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;', output)
            self.assertNotIn('<img src=x', output)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)
        self.assertIn('&lt;em&gt;嘉宾&lt;/em&gt;', page)
        self.assertNotIn('<em>嘉宾</em>', page)
        self.assertIn('2030 年 5 月 1 日 — 2030 年 5 月 2 日', page)
        self.assertIn('2029-12-01T00:00:00Z', page)
        self.assertIn('https://example.com/announcement', page)
        self.assertIn('https://example.com/ticket', page)
        self.assertIn('https://example.com/map', page)
        self.assertIn(BASE + 'feeds/cities/110100.ics', page)
        self.assertIn('href="../index.html#city-110100"', page)
        self.assertIn('href="../assets/site.css"', page)

    def test_published_history_guards_and_city_lock(self):
        self.write_events([sample()])
        self.publish()
        baseline = self.feed()
        for changed in ([], [sample(city_code="310100", revision=1, updated_at="2029-12-02T00:00:00Z")],
                        [sample(revision=1)], [sample(revision=0, title="更名")],
                        [sample(revision=1, title="更名")]):
            self.write_events(changed)
            with self.subTest(changed=changed), self.assertRaises(InputError):
                self.publish()
            self.assertEqual(self.feed(), baseline)
        self.write_events([sample(revision=1, status="cancelled", updated_at="2029-12-02T00:00:00Z")])
        self.publish()
        self.write_events([sample(revision=2, status="confirmed", updated_at="2029-12-03T00:00:00Z")])
        with self.assertRaises(InputError):
            self.publish()

    def test_national_area_catalog_retains_old_links(self):
        self.assertGreater(len(CITY_CODES), 350)
        self.assertEqual(AREA_TO_CITY['110101001000'], '110100')
        self.assertEqual(AREA_TO_CITY['440305001000'], '440300')
        self.assertIn('441900', CITY_CODES)  # 东莞不设县级行政层
        self.assertIn('469001', CITY_CODES)  # 省直管县级市

    def test_township_is_attributed_to_parent_city(self):
        self.write_events([sample(area_code="110101001000")])
        self.publish()
        self.assertEqual(self.feed("110100").count(b"BEGIN:VEVENT"), 1)
        self.write_events([sample(area_code="110101001000", city_code="310100")])
        with self.assertRaises(InputError):
            self.publish()

    def test_verified_opening_hours_and_invalid_ranges(self):
        self.write_events([sample(start_at="2030-05-01T09:30:00+08:00",
                                  end_at="2030-05-02T17:00:00+08:00")])
        self.publish()
        feed = self.feed()
        self.assertIn(b"DTSTART:20300501T013000Z", feed)
        self.assertIn(b"DTEND:20300502T090000Z", feed)
        self.assertIn('北京时间', (self.output / 'events/beijing-001.html').read_text())
        self.write_events([sample(start_at="2030-05-01T09:30:00+08:00")])
        with self.assertRaises(InputError):
            self.publish()

    def test_optional_ticket_map_and_controls(self):
        event = sample(title="A\u0085B")
        self.write_events([event])
        with self.assertRaises(InputError):
            self.publish()
        event = sample()
        del event["ticket_url"]
        del event["map_url"]
        self.write_events([event])
        self.publish()
        self.assertIn(b"URL:https://example.com/announcement", self.feed())
        page = (self.output / "events/beijing-001.html").read_text()
        self.assertNotIn('>票务 ↗</a>', page)
        self.assertNotIn('>导航 ↗</a>', page)

    def test_history_rejects_regression_even_without_local_output(self):
        self.write_events([sample()])
        old = json.dumps({"events": [sample(revision=1, status="cancelled",
                                              updated_at="2029-12-02T00:00:00Z")]}, ensure_ascii=False)
        original = history.events
        with patch.object(history, "events", side_effect=lambda path: original(self.input) if str(path) == "data/events.json" else original(path)), \
             patch.object(history.subprocess, "check_output", side_effect=["abc123\n", old]):
            self.assertEqual(history.main(), 1)

    def test_seed_cannot_publish_unmarked(self):
        with self.assertRaisesRegex(InputError, "require --demo"):
            build.build(base_url=BASE, output=self.output, input_path=build.ROOT / "data/seed_events.json")

    def test_missing_verified_source_is_rejected(self):
        event = sample()
        del event['source_url']
        self.write_events([event])
        with self.assertRaises(InputError):
            self.publish()
        self.assertFalse(self.output.exists())

    def test_missing_optional_guests_and_cancelled_status(self):
        event = sample(status='cancelled')
        del event['guests']
        self.write_events([event])
        self.publish()
        page = (self.output / "events/beijing-001.html").read_text(encoding="utf-8")
        self.assertIn('已取消', page)
        self.assertNotIn('<dt>嘉宾</dt>', page)

    def test_site_render_failure_does_not_replace_old_output(self):
        self.write_events([])
        self.publish()
        before = (self.output / 'index.html').read_bytes()
        with patch.object(build, 'render_site', side_effect=OSError('render failed')):
            with self.assertRaises(OSError):
                self.publish()
        self.assertEqual((self.output / 'index.html').read_bytes(), before)

    def test_duplicate_ids_and_bad_json_refused(self):
        self.write_events([sample(), sample(city_code="310100")])
        with self.assertRaisesRegex(InputError, "duplicate event_id"):
            events(self.input)
        self.input.write_text('{"events":[],"events":[]}', encoding="utf-8")
        with self.assertRaisesRegex(InputError, "duplicate JSON key"):
            events(self.input)

    def test_invalid_base_url_is_rejected_without_publishing(self):
        self.write_events([])
        for url in ("http://example.com/", "https://example.com/sub/../", "https://example.com/a/%GG/"):
            with self.subTest(url=url), self.assertRaises(InputError):
                build.build(base_url=url, output=self.output, input_path=self.input)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
