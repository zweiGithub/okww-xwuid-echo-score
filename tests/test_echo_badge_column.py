"""Synthetic Echo switches: fixed geometry, current badges and complete rows."""
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import test_echo_locked_regions as locked
from test_echo_probability_overlay import panel
from echo_stat_overlay import analyze_echo_stats, EchoStatBoxPainter, StatRectangle


class BadgeColumnTests(unittest.TestCase):
    setUp = locked.LockedRegionTests.setUp
    make_task = locked.LockedRegionTests.make_task

    def set_rows(self, names, values):
        for i, (name, value) in enumerate(zip(names, values)):
            label, number = self.boxes[2+2*i:4+2*i]
            label.name, label.x, label.width = name, 2050, len(name)*28
            number.name = value
        self.base_x = [b.x for b in self.boxes]

    def test_switching_label_lengths_and_order_updates_every_badge(self):
        task = self.make_task()
        self.set_rows(('暴击伤害','攻击','暴击','共鸣技能伤害加成','暴击伤害','重击伤害加成','防御'),
                      ('44.0%','150','6.3%','8.6%','12.6%','10.9%','40'))
        task.run(); cache = task.region_cache; anchors = tuple(task.painter.rectangles)
        self.assertEqual(task.painter.tier_labels[2:], ['1档','4档','1档','7档','1档'])
        self.full_calls = 0
        self.set_rows(('导电伤害加成','攻击','暴击伤害','防御','共鸣效率','暴击','重击伤害加成'),
                      ('30.0%','100','12.6%','60','10.0%','8.1%','9.4%'))
        self.boxes[1].name = 'COST 3'
        task.frame = SimpleNamespace(shape=(1440,2560,3)); self.calls.clear(); task.run()
        self.assertEqual(task.painter.tier_labels[2:], ['1档','3档','5档','4档','5档'])
        self.assertEqual(tuple(task.painter.rectangles), anchors)
        self.assertIs(task.region_cache, cache)
        self.assertEqual(self.full_calls, 0)
        self.assertTrue(all(frame is task.frame for frame, _ in self.calls))
        self.assertIn('当前评分', task.painter.summary)
        self.assertEqual(len({r.tier_x for r in anchors[2:]}), 1)
        for r in anchors[2:]:
            self.assertLessEqual(r.tier_x + 2*r.tier_font_size, min(a.x for a in anchors)-4)

    def test_initial_long_name_cannot_disable_future_valid_badges(self):
        task = self.make_task()
        self.boxes[8].width = 320  # Former per-label placement has no space.
        task.run(); cache = task.region_cache
        self.assertEqual(task.painter.tier_labels[3], '3档')
        self.boxes[8].name = '防御'; self.boxes[8].width = 80; self.boxes[9].name = '60'
        task.run()
        self.assertIs(task.region_cache, cache)
        self.assertEqual(task.painter.tier_labels[3], '3档')

    def test_clean_or_icon_inclusive_boxes_leave_the_icon_gutter_clear(self):
        from test_echo_columns import compact_panel
        for width in (320,640,1000,1280,2048,2560):
            positions=[]
            for clean in (False,True):
                boxes=compact_panel()
                if clean:
                    for b in boxes[2::2]:
                        end=b.x+b.width
                        b.x=2050;b.width=end-b.x;b.name=b.name.lstrip('+')
                scale=width/2560
                for b in boxes:
                    for key in ('x','y','width','height'):
                        setattr(b,key,getattr(b,key)*scale)
                result=analyze_echo_stats(boxes,width,1440*scale,'清宵-通用',show_probability=False)
                for r in result.rectangles[2:]:
                    self.assertLessEqual(r.tier_x+2*r.tier_font_size,2000*scale,(width,clean))
                positions.append(tuple(r.tier_x for r in result.rectangles[2:]))
            self.assertEqual(positions[0],positions[1])

    def test_complete_current_rows_ignore_redundant_guard_disagreement(self):
        task = self.make_task(); task.run(); cache = task.region_cache
        original = task.ocr
        def ocr(frame=None, **bounds):
            result = original(frame=frame, **bounds)
            if bounds and bounds['x']*2560 == cache.guard_roi[0]:
                result = [b for b in result if b.name != '13.8%']
            return result
        task.ocr = ocr; self.full_calls = 0
        self.boxes[11].name = '11.6%'; task.run()
        self.assertIs(task.region_cache, cache)
        self.assertEqual(self.full_calls, 0)
        self.assertIn('当前评分', task.painter.summary)
        self.assertEqual(task.painter.tier_labels[4], '8档')
        self.assertEqual(task.painter.tier_colors[4], (255,75,75))

    def test_complete_rows_do_not_depend_on_guard_pairing_parser(self):
        task = self.make_task(); task.run(); cache = task.region_cache
        with patch('echo_region_cache._find_ocr_rows', side_effect=ValueError('guard pairing')):
            task.run()
        self.assertIs(task.region_cache, cache)
        self.assertIn('当前评分', task.painter.summary)

    def test_partial_rows_still_require_guard_completeness(self):
        task = self.make_task(4); task.run(); cache = task.region_cache
        with patch('echo_region_cache._find_ocr_rows', side_effect=ValueError('guard pairing')):
            task.run()
        self.assertIs(task.region_cache, cache)
        self.assertNotIn('当前评分', task.painter.summary)
        self.assertIn('完整性未确认', task.painter.summary)

    def test_complete_rows_still_require_fresh_metadata_and_valid_rows(self):
        task = self.make_task(); task.run(); cache = task.region_cache
        self.boxes[1].name = 'COST14'; task.run()
        self.assertIs(task.region_cache, cache)
        self.assertNotIn('当前评分', task.painter.summary)
        self.boxes[1].name = 'COST 4'; self.boxes[11].name = '8.3%'; task.run()
        self.assertIsNone(task.region_cache)
        self.assertEqual(task.painter.tier_labels, [])
        self.assertNotIn('当前评分', task.painter.summary)

    def test_badge_column_fits_small_viewports_without_touching_row_or_score(self):
        for width in (320,640,1000):
            boxes = panel()
            for b in boxes:
                for key in ('x','y','width','height'):
                    setattr(b,key,getattr(b,key)*width/1000)
            result = analyze_echo_stats(boxes,width,width,'清宵-通用',show_probability=False)
            self.assertEqual(result.tier_labels[2:], ('1档','1档'))
            for r in result.rectangles[2:]:
                self.assertGreaterEqual(r.tier_x,0)
                self.assertGreater(r.tier_font_size,0)
                self.assertLessEqual(r.tier_x+2*r.tier_font_size,r.x-4)
                self.assertGreaterEqual(r.tier_y,r.y)
                self.assertLessEqual(r.tier_y+r.tier_font_size,r.y+r.height)

    def test_painter_honors_zero_badge_x_and_keeps_score_in_other_gutter(self):
        painter = EchoStatBoxPainter()
        painter.update((StatRectangle(45,20,200,28,(255,255,255),0,25,12),),
                       (1.2,), '', ('1档',), ((80,235,130),))
        scores=[]
        canvas=SimpleNamespace(rectangle=lambda *a,**kw:None,
                               text=lambda x,y,text,**kw:scores.append((x,y,text)))
        with patch('echo_stat_overlay._paint_bold_text') as badge:
            painter.paint(canvas,None)
        self.assertEqual(badge.call_args.args[1:3], (0,25))
        self.assertEqual(badge.call_args.args[-1], 12)
        self.assertEqual(scores, [(253,20,'+1.20')])

    def test_seven_slots_never_bypass_invalid_or_duplicate_dedicated_text(self):
        for name,value in (('生命错误','6.4%'),('暴击伤害','13.8%'),('生命','6.4')):
            with self.subTest(name=name,value=value):
                task=self.make_task();task.run()
                self.boxes[6].name=name;self.boxes[7].name=value
                task.run()
                self.assertIsNone(task.region_cache)
                self.assertEqual(task.painter.tier_labels, [])
                self.assertNotIn('当前评分',task.painter.summary)
