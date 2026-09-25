import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from src.model import ROOT, events, https_url


class AICollectionTests(unittest.TestCase):
    def test_first_official_comic_expo_has_evidence(self):
        record = next(row for row in events(ROOT / 'data/events.json')
                      if row['event_id'] == 'ai-cicf-agf-guangzhou-2026')
        self.assertEqual((record['start_date'], record['end_date']), ('2026-10-02', '2026-10-06'))
        self.assertEqual(record['city_code'], '440100')
        self.assertEqual(urlsplit(record['source_url']).hostname, 'www.cicfexpo.com')
        evidence = json.loads((ROOT / 'data/collection_evidence/2026-09-25-cicf-agf.json').read_text())
        source = next(row for row in evidence['accepted'] if row['event_id'] == record['event_id'])
        self.assertEqual(record['source_url'], source['organizer_announcement'])
        for field in ('organizer_announcement', 'organizer_date_and_venue_crosscheck',
                      'venue_address_crosscheck'):
            https_url(source[field], field)

    def test_project_skill_is_discoverable(self):
        skill = (ROOT / '.pi/skills/comic-event-collector/SKILL.md').read_text()
        self.assertTrue(skill.startswith('---\nname: comic-event-collector\ndescription: '))
        self.assertIn('references/evidence-format.md', skill)
        self.assertIn('不绕过登录', skill)
        self.assertIn('不会使 GitHub Actions 获得 AI 搜索能力', skill)


if __name__ == '__main__':
    unittest.main()
