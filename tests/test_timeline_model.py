from dataclasses import replace
import json
import unittest
from ne501.timeline_model import Clip, Timeline, example_timeline, format_time, tick_from_seconds


class TimelineModelTests(unittest.TestCase):
    def setUp(self): self.timeline = example_timeline()

    def test_tenths_and_formatting(self):
        self.assertEqual(tick_from_seconds(0.1), 1)
        self.assertEqual(format_time(1200), '02:00.0')
        self.assertEqual(format_time(36000), '01:00:00.0')
        for bad in (0.15, float('nan'), '3', True):
            with self.assertRaises(ValueError): tick_from_seconds(bad)

    def test_overlap_rejected_without_changing_model(self):
        old = self.timeline.get('a')
        with self.assertRaisesRegex(ValueError, '重疊'):
            self.timeline.replace(replace(old, start=400, end=600))
        self.assertEqual(self.timeline.get('a'), old)
        self.timeline.replace(replace(old, start=250, end=550))
        self.assertEqual(self.timeline.get('a').end, 550)  # touching is allowed
        self.assertTrue(any(c.pump == 1 for c in self.timeline.active(250)))

    def test_four_units_and_direction(self):
        expected = [('µL/min', 10, 300, 5), ('mL/min', 0.1, 600, 100),
                    ('µL/hr', 60, 600, 1), ('mL/hr', 1, 36000, 1000)]
        for unit, rate, end, volume in expected:
            with self.subTest(unit=unit):
                self.assertAlmostEqual(Clip('x', 0, 0, end, 'WDR', rate, unit).volume_ul, volume)
        for bad in (0, -1, float('inf'), float('nan'), 0.00001):
            with self.assertRaises(ValueError): self.timeline.replace(replace(self.timeline.get('a'), rate=bad))

    def test_gap_finding_and_no_silent_truncation(self):
        c = self.timeline.make_clip(0, 300, 150)
        self.assertEqual((c.start, c.end), (300, 450))
        self.timeline.add(c)
        with self.assertRaises(ValueError): self.timeline.make_clip(0, 800, 500)

    def test_json_roundtrip_and_custom_address_mapping(self):
        timeline = example_timeline([5, 7, 8, 9])
        restored = Timeline.from_json(timeline.to_json())
        self.assertEqual(restored.addresses, [5, 7, 8, 9])
        self.assertEqual(restored.clips, sorted(timeline.clips, key=lambda c: (c.pump, c.start)))
        self.assertEqual(timeline.copy().addresses, [5, 7, 8, 9])
        with self.assertRaises(ValueError): example_timeline([0, 0, 2, 3])

    def test_browser_preview_format_compatible_and_invalid_rejected(self):
        data = json.loads(self.timeline.to_json())
        data['tracks'][0]['blocks'][0]['start'] = 0.15
        with self.assertRaises(ValueError): Timeline.from_json(json.dumps(data))
        with self.assertRaises(ValueError): Timeline.from_json('{bad json')
        data = json.loads(self.timeline.to_json()); data['tracks'][1]['address'] = data['tracks'][0]['address']
        with self.assertRaises(ValueError): Timeline.from_json(json.dumps(data))

    def test_change_total_rejects_cutting_off_any_block(self):
        with self.assertRaises(ValueError): self.timeline.set_total(1000)
        self.assertEqual(self.timeline.total, 1200)
        self.timeline.set_total(1300)
        self.assertEqual(self.timeline.total, 1300)


if __name__ == '__main__': unittest.main()
