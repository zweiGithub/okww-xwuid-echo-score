"""Locking depends on processable row text, not auxiliary OCR geometry."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import test_echo_locked_regions as locked


class ReadableLockTests(unittest.TestCase):
    setUp=locked.LockedRegionTests.setUp
    make_task=locked.LockedRegionTests.make_task

    def test_missing_cost_still_locks_rows_without_a_precise_score(self):
        task=self.make_task();self.boxes[1].name='unreadable';task.run()
        self.assertIsNotNone(task.region_cache)
        first=tuple(task.painter.rectangles)
        self.assertNotIn('当前评分',task.painter.summary)
        self.assertIn('COST',task.painter.summary)
        self.full_calls=0
        for b in self.boxes[2:]:b.y+=2
        task.run()
        self.assertEqual(tuple(task.painter.rectangles),first)
        self.assertEqual(self.full_calls,0)

    def test_missing_page_marker_does_not_unlock_successful_rows(self):
        task=self.make_task();task.run();first=tuple(task.painter.rectangles);self.full_calls=0
        self.boxes[0].name='unreadable';task.run()
        self.assertEqual(tuple(task.painter.rectangles),first)
        self.assertEqual(self.full_calls,0)
        self.assertIsNotNone(task.region_cache)
        self.assertNotIn('当前评分',task.painter.summary)
        self.assertIn('页面',task.painter.summary)

    def test_guard_conflict_changes_status_not_geometry_or_cached_rois(self):
        task=self.make_task();task.run();cache=task.region_cache;self.full_calls=0
        original=task.ocr
        def ocr(frame=None,**bounds):
            result=original(frame=frame,**bounds)
            if bounds and bounds['x']*2560==cache.guard_roi[0]:
                for b in result:
                    if b.name=='10.9%':b.name='8.6%'
            return result
        task.ocr=ocr;task.run()
        self.assertIs(task.region_cache,cache)
        self.assertEqual(tuple(task.painter.rectangles),cache.rectangles)
        self.assertEqual(self.full_calls,0)

    def test_bbox_noise_cannot_unlock_rows_or_toggle_tier_visibility(self):
        task=self.make_task();task.run();first=tuple(task.painter.rectangles)
        tiers=tuple(task.painter.tier_labels);self.full_calls=0;original=task.ocr
        def ocr(frame=None,**bounds):
            result=original(frame=frame,**bounds)
            if bounds:
                for b in result:
                    b.x-=6;b.width+=12;b.y-=2;b.height+=4
            return result
        task.ocr=ocr;task.run()
        self.assertEqual(tuple(task.painter.rectangles),first)
        self.assertEqual(tuple(task.painter.tier_labels),tiers)
        self.assertEqual(self.full_calls,0)

    def test_valid_cached_rows_survive_guard_exception_without_stale_scoring(self):
        task=self.make_task();task.run();cache=task.region_cache;self.full_calls=0
        original=task.ocr
        def ocr(frame=None,**bounds):
            if bounds and bounds['x']*2560==cache.guard_roi[0]:raise RuntimeError('metadata OCR failed')
            return original(frame=frame,**bounds)
        task.ocr=ocr;task.run()
        self.assertIs(task.region_cache,cache)
        self.assertEqual(tuple(task.painter.rectangles),cache.rectangles)
        self.assertEqual(self.full_calls,0)
        self.assertNotIn('当前评分',task.painter.summary)

    def test_initial_unknown_page_can_lock_unique_processable_panel_with_status(self):
        task=self.make_task();self.boxes[0].name='unreadable';task.run()
        self.assertIsNotNone(task.region_cache)
        self.assertEqual(len(task.painter.rectangles),7)
        self.assertIn('页面',task.painter.summary)
        self.assertNotIn('当前评分',task.painter.summary)

    def test_guard_missing_one_row_cannot_discard_seven_valid_row_crops(self):
        task=self.make_task();task.run();cache=task.region_cache;self.full_calls=0;original=task.ocr
        def ocr(frame=None,**bounds):
            result=original(frame=frame,**bounds)
            if bounds and bounds['x']*2560==cache.guard_roi[0]:result=[b for b in result if b.y not in (593,596)]
            return result
        task.ocr=ocr;task.run()
        self.assertIs(task.region_cache,cache)
        self.assertEqual(len(task.painter.rectangles),7)
        self.assertEqual(self.full_calls,0)

    def test_clean_unlevelled_two_main_rows_lock_without_substats(self):
        task=self.make_task(2)
        self.boxes[2].name='暴击';self.boxes[3].name='4.4%';self.boxes[5].name='30'
        task.run()
        self.assertIsNotNone(task.region_cache)
        self.assertEqual(len(task.painter.rectangles),2)
        self.assertIn('当前评分',task.painter.summary)
        self.assertNotIn('完整性未确认',task.painter.summary)
        self.full_calls=0;task.run()
        self.assertEqual(self.full_calls,0)

    def test_two_rows_with_unknown_icon_name_still_require_real_confirmation(self):
        task=self.make_task(2)
        self.boxes[2].name='茶暴击';self.boxes[3].name='4.4%';self.boxes[5].name='30'
        task.run()
        self.assertIsNone(task.region_cache)
        self.assertEqual(task.painter.row_scores,[])
        self.assertIn('完整性未确认',task.painter.summary)

    def test_unverified_extra_guard_row_cannot_unlock_existing_good_rows(self):
        from test_echo_columns import compact_panel
        task=self.make_task(4);task.run();cache=task.region_cache;self.full_calls=0
        self.boxes=compact_panel()[:12];self.base_x=[b.x for b in self.boxes]
        original=task.ocr
        def ocr(frame=None,**bounds):
            result=original(frame=frame,**bounds)
            if bounds and bounds['x']*2560==cache.guard_roi[0]:
                for b in result:
                    if b.name=='攻击' and b.y==500:b.name='茶攻击'
            return result
        task.ocr=ocr;task.run()
        self.assertIs(task.region_cache,cache)
        self.assertEqual(self.full_calls,0)
        self.assertNotIn('当前评分',task.painter.summary)

    def test_ambiguous_or_malformed_cost_is_unavailable_not_an_inferred_score(self):
        from echo_region_cache import explicit_cost
        from test_echo_probability_overlay import box
        for boxes in ([box('COST14',10,10)],
                      [box('COST',10,10),box('1',100,10),box('COST',300,10),box('4',390,10)],
                      [box('COST 1 COST 4',10,10)]):
            self.assertIsNone(explicit_cost(boxes))
        task=self.make_task();task.run();cache=task.region_cache;self.full_calls=0
        self.boxes[1].name='COST14';task.run()
        self.assertIs(task.region_cache,cache)
        self.assertEqual(self.full_calls,0)
        self.assertIn('COST',task.painter.summary)
        self.assertNotIn('当前评分',task.painter.summary)

    def test_conflicting_cost_outside_recovery_band_does_not_disappear_next_tick(self):
        from test_echo_probability_overlay import panel,box
        task=self.make_task(2);self.boxes=panel(subs=())
        self.boxes[1]=box('COST 1',600,50,80,20)
        self.boxes.append(box('COST 4',800,650,80,20))
        task.frame=SimpleNamespace(shape=(1000,1000,3));calls=[]
        def ocr(frame=None,**bounds):
            calls.append(bounds)
            if not bounds:return deepcopy(self.boxes)
            return [deepcopy(b) for b in self.boxes if b.x>=bounds['x']*1000-.01 and b.y>=bounds['y']*1000-.01
                    and b.x+b.width<=bounds['to_x']*1000+.01 and b.y+b.height<=bounds['to_y']*1000+.01]
        task.ocr=ocr;task.run();cache=task.region_cache;calls.clear()
        self.assertIsNotNone(cache)
        self.assertNotIn('当前评分',task.painter.summary)
        task.run()
        self.assertIs(task.region_cache,cache)
        self.assertTrue(all(calls))
        self.assertNotIn('当前评分',task.painter.summary)

    def test_auto_template_carryover_remains_usable_without_new_equipped_marker(self):
        task=self.make_task();task.auto_matched_template='清宵-通用'
        self.settings['自动匹配评分模板']=True
        task.run()
        self.assertIn('当前评分',task.painter.summary)
        self.assertIn('清宵',task.painter.summary)

    def test_longer_new_label_hides_tier_without_moving_any_anchor(self):
        task=self.make_task();task.run();first=tuple(task.painter.rectangles);self.full_calls=0
        self.boxes[6].name='共鸣解放伤害加成';self.boxes[6].width=290;self.boxes[7].name='7.9%'
        task.run()
        self.assertEqual(tuple(task.painter.rectangles),first)
        self.assertEqual(self.full_calls,0)
        self.assertEqual(task.painter.tier_labels[2],'')

    def test_score_unavailable_does_not_break_latched_tier_geometry(self):
        from unittest.mock import patch
        task=self.make_task()
        with patch('echo_stat_overlay.calculate_echo_score',return_value=None):task.run()
        self.assertIsNotNone(task.region_cache)
        first=tuple(task.painter.rectangles)
        task.run()
        self.assertEqual(tuple(task.painter.rectangles),first)
        self.assertIn('当前评分',task.painter.summary)
