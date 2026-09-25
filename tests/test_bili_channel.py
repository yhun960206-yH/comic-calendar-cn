"""Bilibili 频道适配器的契约测试。

全部离线运行：HTTP 层被替换成假响应，不访问 B 站。
"""
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.sources import bili_channel as bili
from src.sources import pipeline

BASE = 'https://example.github.io/comic-calendar-cn/'
OBSERVED = '2026-09-25T00:00:00Z'


def row(pid=1006385, city_id=350200, name='厦门·某同人ONLY', start='2026-10-04', end=None,
        venue='Ovogo旺来现场', category='漫展', district='湖里区'):
    return {'id': pid, 'cityId': city_id, 'project_name': name, 'start_time': start,
            'end_time': end or start, 'venue_name': venue, 'third_category_name': category,
            'district_name': district, 'coordinate': json.dumps({'type': 'GD', 'coor': '118.09,24.51'})}


def detail(street='华昌路132号-1号104室', guests=('蜂鸟', '小和田猫猫'), coor='118.09,24.51'):
    return {'venue_info': {'name': 'Ovogo旺来现场', 'address_detail': street,
                           'province_name': '福建', 'city_name': '厦门',
                           'coordinate': {'type': 'GD', 'coor': coor}},
            'guests': [{'name': name} for name in guests]}


class Response:
    def __init__(self, url, payload):
        self.url = url
        self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def geturl(self): return self.url
    def read(self, size=0): return json.dumps(self.payload).encode()[:size or None]


class NormalizeTests(unittest.TestCase):
    def test_maps_city_id_and_makes_end_date_exclusive(self):
        candidate, reason = bili.normalize(row(start='2026-10-04', end='2026-10-06'), detail(), OBSERVED)
        self.assertIsNone(reason)
        self.assertEqual(candidate['city_code'], '350200')
        self.assertEqual(candidate['start_date'], '2026-10-04')
        self.assertEqual(candidate['end_date'], '2026-10-07')  # 最后一天次日
        self.assertEqual(candidate['event_id'], 'bili-1006385')
        self.assertEqual(candidate['venue_address'], '福建省厦门市华昌路132号-1号104室')
        self.assertEqual(candidate['guests'], ['蜂鸟', '小和田猫猫'])
        self.assertTrue(candidate['map_url'].startswith('https://uri.amap.com/marker?position='))
        self.assertEqual(candidate['source_url'], candidate['ticket_url'])

    def test_municipality_address_is_not_duplicated(self):
        candidate, _ = bili.normalize(row(city_id=310100, name='上海·某Only'), detail(street='申昆路1988号A栋'), OBSERVED)
        self.assertEqual(candidate['venue_address'], '上海市申昆路1988号A栋')

    def test_cancelled_marker_is_recorded_not_dropped(self):
        candidate, _ = bili.normalize(row(name='厦门·某展（取消）'), detail(), OBSERVED)
        self.assertEqual(candidate['status'], 'cancelled')
        self.assertNotIn('取消', candidate['title'])

    def test_missing_detail_still_yields_a_record(self):
        candidate, reason = bili.normalize(row(), None, OBSERVED)
        self.assertIsNone(reason)
        self.assertNotIn('guests', candidate)

    def test_rejects_unknown_city_and_bad_dates(self):
        self.assertEqual(bili.normalize(row(city_id=999999), detail(), OBSERVED)[1], "unsupported cityId '999999'")
        self.assertEqual(bili.normalize(row(start=None), detail(), OBSERVED)[1], 'missing or malformed dates')
        self.assertEqual(bili.normalize(row(start='2026-10-06', end='2026-10-04'), detail(), OBSERVED)[1],
                         'end date before start')
        self.assertEqual(bili.normalize(row(venue=''), None, OBSERVED)[1], 'venue or address not published')

    def test_guests_are_cleaned_and_deduplicated(self):
        candidate, _ = bili.normalize(row(), detail(guests=('  蜂鸟 ', '蜂鸟', '', '\t')), OBSERVED)
        self.assertEqual(candidate['guests'], ['蜂鸟'])


class FetchTests(unittest.TestCase):
    def pages(self, sizes, last=True, code=0):
        """按页返回假列表接口响应。"""
        calls = {'n': 0}
        def open_list(request, timeout):
            index = calls['n']
            calls['n'] += 1
            size = sizes[min(index, len(sizes) - 1)]
            base = index * 100
            payload = {'code': code, 'message': 'success' if code == 0 else 'rejected',
                       'data': {'isLastBrush': last and index >= len(sizes) - 1,
                                'result': [row(pid=pid) for pid in range(base, base + size)]}}
            return Response(request.full_url, payload)
        return open_list, calls

    def test_fingerprint_failure_is_hard(self):
        def open_spi(request, timeout):
            return Response(request.full_url, {'code': 0, 'data': {}})
        with self.assertRaises(bili.BiliSourceError):
            bili.mint_cookie(opener=open_spi)

    def test_takes_the_longest_pass_when_the_endpoint_truncates_early(self):
        """接口会偶发提前宣告末页：900 与 1144 两种结果取多的那一次。"""
        lengths = [[5, 5], [9, 9], [9, 9]]
        calls = {'n': 0}
        def open_list(request, timeout):
            index = calls['n']
            calls['n'] += 1
            sizes = lengths[min(index, len(lengths) - 1)]
            payload = {'code': 0, 'message': 'success',
                       'data': {'isLastBrush': index % 2 == 1, 'result': [row(pid=pid) for pid in range(0, sizes[0])]}}
            return Response(request.full_url, payload)
        with patch.object(bili.time, 'sleep', lambda *_: None):
            rows = bili.fetch_list('cookie', opener=open_list, pause=0)
        self.assertEqual(len(rows), 9)

    def test_stalled_pagination_is_refused(self):
        def open_list(request, timeout):
            payload = {'code': 0, 'message': 'success',
                       'data': {'isLastBrush': False, 'result': [row(pid=1)]}}
            return Response(request.full_url, payload)
        with self.assertRaises(bili.BiliSourceError):
            bili._crawl_once('cookie', opener=open_list, pause=0)

    def test_nonzero_code_is_refused(self):
        def open_list(request, timeout):
            return Response(request.full_url, {'code': 81102084, 'message': 'bad param', 'data': {}})
        with self.assertRaises(bili.BiliSourceError):
            bili._crawl_once('cookie', opener=open_list, pause=0)


class PruneTests(unittest.TestCase):
    def test_only_long_expired_bilibili_records_are_dropped(self):
        previous = [
            {'event_id': 'bili-1', 'end_date': '2026-01-01'},
            {'event_id': 'bili-2', 'end_date': '2026-09-20'},
            {'event_id': 'fec-web-1', 'end_date': '2026-01-01'},
            {'event_id': 'ai-cicf-agf-guangzhou-2026', 'end_date': '2026-01-01'},
        ]
        kept, dropped = bili.prune_expired(previous, today=date(2026, 9, 25), keep_days=30)
        self.assertEqual(dropped, 1)
        self.assertEqual([e['event_id'] for e in kept], ['bili-2', 'fec-web-1', 'ai-cicf-agf-guangzhou-2026'])


class CheckpointResponse:
    def __init__(self, request, events):
        self.url = request.full_url
        self.events = events
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def geturl(self): return self.url
    def read(self, size): return json.dumps({'demo': False, 'events': self.events}).encode()[:size]


class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.local = Path(self.temp.name) / 'local.json'
        self.output = Path(self.temp.name) / 'candidate.json'
        self.local.write_text('{"events":[]}', encoding='utf-8')

    def opener(self, events):
        def open_checkpoint(request, timeout):
            return CheckpointResponse(request, events)
        return open_checkpoint

    def candidate(self, pid):
        return {'event_id': f'bili-{pid}', 'revision': 0, 'status': 'confirmed', 'city_code': '350200',
                'title': f'活动 {pid}', 'start_date': '2026-10-04', 'end_date': '2026-10-05',
                'updated_at': OBSERVED, 'venue_name': '场馆', 'venue_address': '福建省厦门市某路1号',
                'source_url': f'https://show.bilibili.com/platform/detail.html?id={pid}'}

    def test_bilibili_candidates_are_merged_with_the_checkpoint(self):
        report = pipeline.prepare_multi(BASE, '', self.local, self.output, use_web=False, use_bili=True,
                                        opener=self.opener([]), bili_fetch=lambda previous=None: ([self.candidate(1)], [], OBSERVED))
        self.assertEqual(report['bilibili']['eligible'], 1)
        self.assertEqual(report['eligible_events'], 1)
        self.assertEqual(json.loads(self.output.read_text())['events'][0]['event_id'], 'bili-1')

    def test_sharp_drop_in_bilibili_results_stops_publication(self):
        with self.assertRaises(pipeline.SourceError):
            pipeline.prepare_multi(BASE, '', self.local, self.output, use_web=False, use_bili=True,
                                   opener=self.opener([self.candidate(pid) for pid in range(100)]),
                                   bili_fetch=lambda previous=None: ([self.candidate(1)], [], OBSERVED))
        self.assertFalse(self.output.exists())

    def test_source_failure_leaves_no_candidate(self):
        def boom(previous=None):
            raise bili.BiliSourceError('fingerprint unavailable')
        with self.assertRaises(bili.BiliSourceError):
            pipeline.prepare_multi(BASE, '', self.local, self.output, use_web=False, use_bili=True,
                                   opener=self.opener([]), bili_fetch=boom)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
