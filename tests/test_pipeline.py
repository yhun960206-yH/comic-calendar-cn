import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

from src.sources import fec, pipeline
from test_fec import row

BASE = 'https://example.github.io/comic-calendar-cn/'


class CheckpointResponse:
    def __init__(self, request, events):
        self.url = request.full_url
        self.events = events
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def geturl(self): return self.url
    def read(self, size):
        return json.dumps({'demo': False, 'events': self.events}).encode()[:size]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.local = Path(self.temp.name) / 'local.json'
        self.output = Path(self.temp.name) / 'candidate.json'
        self.local.write_text('{"events":[]}', encoding='utf-8')

    def opener(self, events):
        def open_checkpoint(request, timeout):
            self.assertEqual(timeout, 20)
            return CheckpointResponse(request, events)
        return open_checkpoint

    def test_missing_key_never_writes_and_valid_run_creates_candidate(self):
        with self.assertRaises(pipeline.SourceError):
            pipeline.prepare(BASE, '', self.local, self.output, opener=self.opener([]))
        self.assertFalse(self.output.exists())
        report = pipeline.prepare(BASE, 'test-key', self.local, self.output,
                                  opener=self.opener([]), source_fetch=lambda key: [row()], run_id='42')
        result = json.loads(self.output.read_text())
        self.assertEqual(result['events'][0]['city_code'], '440300')
        self.assertEqual(report['source_rows'], 1)
        self.assertEqual(len(result['events']), 1)

    def test_source_failure_and_all_quarantined_leave_output_untouched(self):
        self.output.write_text('previous')
        for fetch in (lambda key: (_ for _ in ()).throw(pipeline.SourceError('HTTP 401')),
                      lambda key: [row(address='')]):
            with self.assertRaises(pipeline.SourceError):
                pipeline.prepare(BASE, 'test-key', self.local, self.output,
                                 opener=self.opener([]), source_fetch=fetch)
            self.assertEqual(self.output.read_text(), 'previous')

    def test_later_run_reuses_uid_and_increments_revision(self):
        with patch.object(pipeline, 'datetime') as clock:
            clock.now.side_effect = [datetime(2029, 1, 1, tzinfo=timezone.utc),
                                     datetime(2029, 1, 2, tzinfo=timezone.utc)]
            pipeline.prepare(BASE, 'key', self.local, self.output,
                             opener=self.opener([]), source_fetch=lambda key: [row()])
            old = json.loads(self.output.read_text())['events']
            pipeline.prepare(BASE, 'key', self.local, self.output,
                             opener=self.opener(old), source_fetch=lambda key: [row(name='更新后的名称')])
        new = json.loads(self.output.read_text())['events']
        self.assertEqual(new[0]['event_id'], old[0]['event_id'])
        self.assertEqual(new[0]['revision'], old[0]['revision'] + 1)
        self.assertEqual(new[0]['title'], '更新后的名称')

    def test_check_no_key_refuses_to_erase_live_api_events(self):
        candidate, _ = fec.reconcile(
            [], [row()], '2029-01-01T00:00:00Z')
        with patch.object(pipeline, 'load_published', return_value=candidate):
            self.assertEqual(pipeline.main(['--base-url', BASE, '--check-no-key']), 1)
        with patch.object(pipeline, 'load_published', return_value=[]):
            self.assertEqual(pipeline.main(['--base-url', BASE, '--check-no-key']), 0)


if __name__ == '__main__':
    unittest.main()
