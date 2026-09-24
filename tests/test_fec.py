import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from src.sources import fec
from src.model import events


class Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.payload).encode()


def row(**changes):
    event = {"id": "0b448a05-fefe-444c-a9dd-81b21ea785c3", "name": "兽展样例",
             "region": "深圳", "address": "广东省深圳市南山区演示展馆",
             "startDate": "2030-05-01T01:30:00.000Z", "endDate": "2030-05-01T09:00:00.000Z",
             "status": "scheduled", "url": "https://www.furrycons.cn/org/2030-con"}
    event.update(changes)
    return event


class FECTests(unittest.TestCase):
    def test_api_requires_key_and_checks_schema(self):
        with self.assertRaises(fec.SourceError): fec.fetch_all("")
        def good(req, timeout):
            self.assertEqual(req.get_header('Authorization'), 'test-key')
            self.assertEqual(timeout, 20)
            return Response({'total': 1, 'data': [row()]})
        self.assertEqual(len(fec.fetch_all('test-key', opener=good)), 1)
        def denied(req, timeout): raise HTTPError(req.full_url, 401, 'no key', {}, None)
        with self.assertRaises(fec.SourceError): fec.fetch_all('bad', opener=denied)
        with self.assertRaises(fec.SourceError): fec.fetch_all('test-key', opener=lambda *_ , **__: Response({'data': []}))

    def test_incomplete_venue_quarantined_not_published(self):
        result, reason = fec.normalize(row(address=''), '2030-01-01T00:00:00Z')
        self.assertIsNone(result)
        self.assertIn('venue', reason)
        result, reason = fec.normalize(row(region='广东省'), '2030-01-01T00:00:00Z')
        self.assertIsNone(result)
        self.assertIn('region', reason)

    def test_city_time_revision_attribution_and_missing_event_retained(self):
        now = '2030-01-01T00:00:00Z'
        merged, skipped = fec.reconcile([], [row()], now)
        self.assertFalse(skipped)
        event = merged[0]
        self.assertEqual(event['city_code'], '440300')
        self.assertEqual(event['start_at'], '2030-05-01T09:30:00+08:00')
        self.assertEqual(event['end_date'], '2030-05-02')
        self.assertEqual(event['revision'], 0)
        self.assertIn('CC BY-SA', event['attribution'])
        same, _ = fec.reconcile(merged, [row()], '2030-01-02T00:00:00Z')
        self.assertEqual(same, merged)
        changed, _ = fec.reconcile(same, [row(name='兽展改名')], '2030-01-03T00:00:00Z')
        self.assertEqual(changed[0]['revision'], 1)
        self.assertEqual(changed[0]['event_id'], event['event_id'])
        retained, _ = fec.reconcile(changed, [], '2030-01-04T00:00:00Z')
        self.assertEqual(retained, changed)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.json'
            path.write_text(json.dumps({'events': changed}, ensure_ascii=False))
            self.assertEqual(events(path), changed)

    def test_unknown_status_and_city_change_do_not_mutate_old_event(self):
        old, _ = fec.reconcile([], [row()], '2030-01-01T00:00:00Z')
        updated, quarantine = fec.reconcile(old, [row(status='unexpected'), row(region='上海')],
                                            '2030-01-02T00:00:00Z')
        self.assertEqual(updated, old)
        self.assertEqual(len(quarantine), 2)

    def test_no_key_does_not_write_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'candidates.json'
            with patch.dict('os.environ', {'FEC_API_KEY': ''}):
                self.assertEqual(fec.main(['--output', str(output)]), 1)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
