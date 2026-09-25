import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.sources import fec_web, pipeline

BASE = 'https://example.github.io/comic-calendar-cn/'
EVENT_URL = 'https://www.furrycons.cn/organizer/2027-jan-test-con'


def event_html(*, address='南京市鼓楼区测试展馆', city='南京', status='EventScheduled'):
    event = {'@context': 'https://schema.org', '@type': 'Event', 'name': '同人主题',
             'startDate': '2027-01-01T16:00:00.000Z', 'endDate': '2027-01-03T16:00:00.000Z',
             'eventStatus': 'https://schema.org/' + status,
             'location': {'@type': 'Place', 'name': '测试展馆',
                          'address': {'@type': 'PostalAddress', 'addressCountry': 'CN',
                                      'addressLocality': city, 'streetAddress': address}}}
    return '<script type="application/ld+json">' + json.dumps(event, ensure_ascii=False) + '</script>'


class Response:
    def __init__(self, url, html): self.url, self.html = url, html
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def geturl(self): return self.url
    def read(self, limit): return self.html.encode()[:limit]


class WebTests(unittest.TestCase):
    def opener(self, request, timeout):
        self.assertEqual(timeout, 20)
        if request.full_url == fec_web.HOME:
            return Response(request.full_url, '<a href="/organizer/2027-jan-test-con">综合性展会南京</a>'
                                          '<a href="/other/2027-jan-party">专项聚会</a>')
        if request.full_url == EVENT_URL:
            return Response(request.full_url, event_html())
        raise AssertionError('unexpected request ' + request.full_url)

    def test_public_site_structured_expo_and_inclusive_last_day(self):
        ready, quarantine, observed = fec_web.fetch_candidates(opener=self.opener, pause=0)
        self.assertEqual(len(ready), 1)
        self.assertFalse(quarantine)
        self.assertEqual(ready[0]['city_code'], '320100')
        self.assertEqual(ready[0]['title'], '兽展 · 同人主题')
        self.assertEqual(ready[0]['start_date'], '2027-01-02')
        self.assertEqual(ready[0]['end_date'], '2027-01-05')
        self.assertNotIn('start_at', ready[0])  # Date-only; no invented opening hours.
        self.assertIn('CC BY-SA', ready[0]['attribution'])
        self.assertTrue(observed.endswith('Z'))

    def test_quarantine_incomplete_and_fail_closed_on_total_loss(self):
        page = fec_web.PublicHTML()
        page.feed(event_html(address=''))
        candidate, reason = fec_web.normalize_event(page, EVENT_URL, '2027-01-01T00:00:00Z')
        self.assertIsNone(candidate)
        self.assertIn('missing', reason)
        with self.assertRaises(fec_web.WebSourceError):
            fec_web.event_links(fec_web.PublicHTML())
        with self.assertRaises(fec_web.WebSourceError):
            fec_web.fetch_html('https://evil.example/test', opener=self.opener)

    def test_web_pipeline_preserves_published_uid_and_without_key(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'events.json'
            output = Path(directory) / 'candidate.json'
            source.write_text('{"events": []}')
            ready, skipped, observed = fec_web.fetch_candidates(opener=self.opener, pause=0)
            with patch.object(pipeline, 'load_published', return_value=[]):
                report = pipeline.prepare_web(BASE, source, output,
                                               web_fetch=lambda: (ready, skipped, observed))
            self.assertEqual(report['eligible_events'], 1)
            first = json.loads(output.read_text())['events']
            with patch.object(pipeline, 'load_published', return_value=first):
                report = pipeline.prepare_web(BASE, source, output,
                                               web_fetch=lambda: (ready, skipped, observed))
            self.assertEqual(json.loads(output.read_text())['events'], first)
            self.assertEqual(report['eligible_events'], 1)


if __name__ == '__main__':
    unittest.main()
