"""Frozen OCR regions and drawing anchors with fresh per-frame content."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_echo_probability_host as host
from test_echo_columns import compact_panel
from test_echo_probability_overlay import box


class LockedRegionTests(unittest.TestCase):
    setUp = host.HostIntegrationTests.setUp

    def make_task(self, count=7):
        self.task_module=host.load_module('echo_score_task')
        task=self.task_module.EchoScoreOverlayTask()
        self.boxes=compact_panel()[:2+count*2]
        self.calls=[];self.full_calls=0;self.fail_crops=False;self.fail_all=False
        self.settings={'角色评分模板':'清宵-通用','显示调谐概率':False}
        task.frame=SimpleNamespace(shape=(1440,2560,3))
        def ocr(frame=None,**bounds):
            self.calls.append((frame,dict(bounds)))
            if not bounds:
                self.full_calls+=1
                return [] if self.fail_all else deepcopy(self.boxes)
            if self.fail_all or self.fail_crops:return []
            h,w=frame.shape[:2]
            left,top,right,bottom=(bounds['x']*w,bounds['y']*h,bounds['to_x']*w,bounds['to_y']*h)
            result=[]
            for i,p in enumerate(self.boxes):
                b=deepcopy(p)
                if i>=2 and i%2==0:
                    b.name=b.name.lstrip('+茶×')
                    # Physical text starts after the icon; crops must contain it.
                    b.x=2050+(p.x-self.base_x[i]);b.width=p.x+p.width-b.x
                if b.x>=left-.01 and b.y>=top-.01 and b.x+b.width<=right+.01 and b.y+b.height<=bottom+.01:
                    result.append(b)
            return result
        self.base_x=[b.x for b in self.boxes]
        task.ocr=ocr
        overlay=SimpleNamespace(draw=lambda *a:None,clear_draw=lambda *a:None)
        task._ensure_overlay=lambda:overlay;task.get_overlay_view=lambda:overlay
        task._settings=lambda:self.settings
        self.addCleanup(task.on_destroy)
        return task

    def test_success_locks_all_geometry_and_never_runs_full_locator_again(self):
        task=self.make_task();task.run();first=tuple(task.painter.rectangles)
        first_scores=tuple(task.painter.row_scores)
        self.calls.clear();self.full_calls=0
        # OCR coordinates can move inside a valid crop. They must not move paint.
        for p in self.boxes[2:]:p.y+=2
        self.boxes[11].name='8.6%'
        task.frame=SimpleNamespace(shape=(1440,2560,3))
        task.run()
        self.assertEqual(tuple(task.painter.rectangles),first)
        self.assertNotEqual(tuple(task.painter.row_scores),first_scores)
        self.assertEqual(self.full_calls,0,'A valid cached read must not run full-screen OCR')
        self.assertTrue(all(frame is task.frame for frame,b in self.calls))
        self.assertTrue(all(bounds for frame,bounds in self.calls))

    def test_repeated_success_preserves_exact_rois_and_all_render_anchors(self):
        task=self.make_task();task.run();first=tuple(task.painter.rectangles)
        self.calls.clear();task.run();regions=[b for f,b in self.calls]
        for jitter in (-2,1,2,-1,0):
            self.calls.clear()
            for i,p in enumerate(self.boxes[2:]):p.y=compact_panel()[i+2].y+jitter
            task.frame=SimpleNamespace(shape=(1440,2560,3));task.run()
            self.assertEqual(tuple(task.painter.rectangles),first)
            self.assertEqual([b for f,b in self.calls],regions)

    def test_failed_cached_read_gets_one_current_frame_reacquisition(self):
        task=self.make_task();task.run();self.full_calls=0;self.calls.clear()
        self.fail_crops=True
        task.run()
        self.assertEqual(self.full_calls,1)
        self.assertTrue(all(f is task.frame for f,b in self.calls))

    def test_failed_reacquisition_clears_old_values(self):
        task=self.make_task();task.run();self.fail_all=True;self.full_calls=0
        task.run()
        self.assertEqual(self.full_calls,1)
        self.assertEqual(task.painter.row_scores,[])
        self.assertEqual(task.painter.rectangles,[])
        self.assertEqual(task.painter.summary,'')

    def test_new_row_outside_old_row_rois_invalidates_cache(self):
        task=self.make_task(4);task.run();self.full_calls=0
        self.boxes=compact_panel()[:12];self.base_x=[b.x for b in self.boxes]
        task.run()
        self.assertEqual(self.full_calls,1)
        self.assertEqual(len(task.painter.rectangles),5)

    def test_fewer_rows_and_page_loss_invalidate_cache(self):
        task=self.make_task();task.run();self.full_calls=0
        self.boxes=self.boxes[:-2];self.base_x=self.base_x[:-2];task.run()
        self.assertEqual(self.full_calls,1)
        self.assertEqual(len(task.painter.rectangles),6)
        self.boxes=[];task.run()
        self.assertEqual(task.painter.summary,'')
        self.assertIsNone(task.region_cache)

    def test_resolution_change_and_disable_clear_cache(self):
        task=self.make_task();task.run();self.full_calls=0
        task.frame=SimpleNamespace(shape=(720,1280,3))
        task.run()
        self.assertEqual(self.full_calls,1)
        self.assertIsNone(task.region_cache)
        task.frame=SimpleNamespace(shape=(1440,2560,3));task.run()
        self.settings['启用声骸评分']=False;task.run()
        self.assertIsNone(task.region_cache)
        self.assertEqual(task.painter.summary,'')

    def test_success_bypasses_column_locator_for_many_frames(self):
        task=self.make_task();task.run();anchors=tuple(task.painter.rectangles)
        self.full_calls=0
        with patch.object(task.layout_tracker,'locate',side_effect=AssertionError('must not locate')):
            for i in range(30):
                self.boxes[11].name='8.6%' if i%2 else '10.9%'
                task.frame=SimpleNamespace(shape=(1440,2560,3));task.run()
                self.assertEqual(tuple(task.painter.rectangles),anchors)
        self.assertEqual(self.full_calls,0)

    def test_another_valid_echo_at_same_positions_updates_name_and_value(self):
        task=self.make_task();task.run();anchors=tuple(task.painter.rectangles)
        scores=tuple(task.painter.row_scores);self.full_calls=0
        self.boxes[2].name='暴击';self.boxes[3].name='22.0%'
        task.run()
        self.assertEqual(self.full_calls,0)
        self.assertEqual(tuple(task.painter.rectangles),anchors)
        self.assertNotEqual(tuple(task.painter.row_scores),scores)
        self.assertNotIn('攻击',repr(task.region_cache))
        self.assertNotIn('26.4%',repr(task.region_cache))

    def test_unknown_current_label_invalidates_instead_of_replaying_name(self):
        task=self.make_task();task.run();self.full_calls=0
        self.boxes[6].name='生命错误'
        task.run()
        self.assertEqual(self.full_calls,1)
        self.assertEqual(task.painter.row_scores,[])
        self.assertIsNone(task.region_cache)
        self.assertIn('识别暂不可用',task.painter.summary)

    def test_zero_substats_can_lock_and_detect_first_unlock(self):
        task=self.make_task(2);task.run();self.full_calls=0
        task.run()
        self.assertEqual(self.full_calls,0)
        self.assertEqual(len(task.painter.rectangles),2)
        self.boxes=compact_panel()[:8];self.base_x=[b.x for b in self.boxes];task.run()
        self.assertEqual(self.full_calls,1)
        self.assertEqual(len(task.painter.rectangles),3)

    def test_full_reacquisition_exception_clears_previous_overlay(self):
        task=self.make_task();task.run()
        def failed(frame=None,**bounds):
            if bounds:return []
            raise RuntimeError('capture OCR failed')
        task.ocr=failed
        task.run()
        self.assertEqual(task.painter.row_scores,[])
        self.assertEqual(task.painter.rectangles,[])
        self.assertIsNone(task.region_cache)

    def test_hidden_game_window_invalidates_geometry_and_display(self):
        task=self.make_task();task.run()
        self.task_module.og=SimpleNamespace(device_manager=SimpleNamespace(
            hwnd_window=SimpleNamespace(exists=True,visible=False)))
        self.calls.clear();task.run()
        self.assertEqual(self.calls,[])
        self.assertIsNone(task.region_cache)
        self.assertEqual(task.painter.summary,'')

    def test_guard_encloses_separate_cost_digit_without_saving_its_value(self):
        task=self.make_task()
        self.boxes[1]=box('COST',2430,210,55,24)
        self.boxes.append(box('4',2510,210,35,24));self.base_x=[b.x for b in self.boxes]
        task.run()
        self.assertIsNotNone(task.region_cache)
        self.assertGreaterEqual(task.region_cache.guard_roi[2],2545)

    def test_unrelated_metadata_cannot_expand_guard_to_full_screen(self):
        task=self.make_task()
        self.boxes += [box('COST 1',40,40,120,25),box('装配中',2400,1320,100,25)]
        self.base_x += [40,2400]
        task.run()
        self.assertIsNotNone(task.region_cache)
        left,top,right,bottom=task.region_cache.guard_roi
        self.assertGreaterEqual(left,2560*.70)
        self.assertLessEqual((right-left)*(bottom-top),2560*1440*.30)

    def test_cached_rois_are_integer_pixel_edges(self):
        task=self.make_task();task.run()
        self.assertTrue(all(isinstance(v,int) for roi in (task.region_cache.guard_roi,*task.region_cache.row_rois) for v in roi))

    def test_guard_conflicting_value_or_label_preserves_lock_and_reports_status(self):
        for kind in ('value','label','unknown'):
            with self.subTest(kind=kind):
                task=self.make_task();task.run();self.full_calls=0
                original=task.ocr;guard=task.region_cache.guard_roi
                def ocr(frame=None,**bounds):
                    result=original(frame=frame,**bounds)
                    if bounds and abs(bounds['x']*2560-guard[0])<.01:
                        candidates=[b for b in result if b.y==500 or b.y==503]
                        for b in candidates:
                            if kind=='value' and b.name=='10.9%':b.name='8.6%'
                            elif kind=='label' and b.name=='攻击':b.name='防御'
                            elif kind=='unknown' and b.name=='攻击':b.name='攻击错误'
                    return result
                task.ocr=ocr;task.run()
                self.assertEqual(self.full_calls,0)
                self.assertIsNotNone(task.region_cache)
                self.assertNotIn('当前评分',task.painter.summary)

    def test_guard_single_icon_candidate_requires_matching_fresh_row_label(self):
        task=self.make_task();task.run();self.full_calls=0
        original=task.ocr;guard=task.region_cache.guard_roi
        def ocr(frame=None,**bounds):
            result=original(frame=frame,**bounds)
            if bounds and abs(bounds['x']*2560-guard[0])<.01:
                for b in result:
                    if b.name=='攻击' and b.y==500:b.name='茶攻击'
            return result
        task.ocr=ocr;task.run()
        self.assertEqual(self.full_calls,0)
        self.assertIn('当前评分',task.painter.summary)

    def test_destroy_clears_cache_even_after_native_overlay_has_disappeared(self):
        task=self.make_task();task.run()
        task.get_overlay_view=lambda:None
        task.on_destroy()
        self.assertIsNone(task.region_cache)
        self.assertIsNone(task.layout_tracker.layout)

    def test_cached_reads_share_captured_frame_even_when_new_frame_arrives(self):
        task=self.make_task();task.run();self.calls.clear()
        original=task.ocr;captured=task.frame
        def ocr(frame=None,**bounds):
            result=original(frame=frame,**bounds)
            task.frame=SimpleNamespace(shape=(720,1280,3))
            return result
        task.ocr=ocr;task.run()
        self.assertEqual(len(self.calls),8)
        self.assertTrue(all(f is captured for f,b in self.calls))
        self.assertIn('当前评分',task.painter.summary)

    def test_last_cached_row_failure_has_bounded_single_fallback(self):
        task=self.make_task();task.run();self.calls.clear();self.full_calls=0
        original=task.ocr;last=task.region_cache.row_rois[-1]
        def ocr(frame=None,**bounds):
            result=original(frame=frame,**bounds)
            if bounds and abs(bounds['y']*1440-last[1])<.01 and abs(bounds['to_x']*2560-last[2])<.01:
                return []
            return result
        task.ocr=ocr;task.run()
        self.assertEqual(self.full_calls,1)
        self.assertLessEqual(len(self.calls),16)
        self.assertIn('当前评分',task.painter.summary)

    def test_explicit_cost_outside_tuning_guard_is_fresh_not_inferred(self):
        from test_echo_probability_overlay import panel
        task=self.make_task(2)
        self.boxes=panel(subs=());self.boxes[1].name='COST 3'
        self.boxes[2].name='攻击';self.boxes[3].name='18.0%';self.boxes[5].name='100'
        task.frame=SimpleNamespace(shape=(1000,1000,3))
        calls=[]
        def ocr(frame=None,**bounds):
            calls.append(bounds)
            if not bounds:return deepcopy(self.boxes)
            return [deepcopy(b) for b in self.boxes if b.x>=bounds['x']*1000-.01 and b.y>=bounds['y']*1000-.01
                    and b.x+b.width<=bounds['to_x']*1000+.01 and b.y+b.height<=bounds['to_y']*1000+.01]
        task.ocr=ocr;task.run();initial=tuple(task.painter.row_scores);calls.clear()
        task.run()
        self.assertEqual(tuple(task.painter.row_scores),initial)
        self.assertTrue(all(calls),'Valid cached metadata must not trigger full-screen OCR')
        self.boxes[1].name='COST 1';self.boxes[5].name='50';calls.clear();task.run()
        self.assertNotEqual(tuple(task.painter.row_scores),initial)
        self.assertTrue(all(calls))
        self.boxes[1].name='COST ?';calls.clear();task.run()
        self.assertEqual(sum(not b for b in calls),0,'Unreadable metadata must not invalidate row geometry')
        self.assertIsNotNone(task.region_cache)
        self.assertNotIn('当前评分',task.painter.summary)

    def test_initially_missing_cost_does_not_lock_out_later_metadata_recovery(self):
        from test_echo_probability_overlay import panel
        task=self.make_task(2)
        self.boxes=panel(subs=());self.boxes[1].name='unreadable'
        self.boxes[2].name='攻击';self.boxes[3].name='18.0%';self.boxes[5].name='75'
        task.frame=SimpleNamespace(shape=(1000,1000,3));calls=[]
        def ocr(frame=None,**bounds):
            calls.append(bounds)
            if not bounds:return deepcopy(self.boxes)
            return [deepcopy(b) for b in self.boxes if b.x>=bounds['x']*1000-.01 and b.y>=bounds['y']*1000-.01
                    and b.x+b.width<=bounds['to_x']*1000+.01 and b.y+b.height<=bounds['to_y']*1000+.01]
        task.ocr=ocr;task.run();initial=tuple(task.painter.row_scores)
        self.assertIsNotNone(task.region_cache)
        self.assertNotIn('当前评分',task.painter.summary)
        self.assertIn('COST',task.painter.summary)
        self.boxes[1].name='COST 3';calls.clear();task.run()
        self.assertEqual(sum(not b for b in calls),0)
        self.assertNotEqual(tuple(task.painter.row_scores),initial)
        self.assertIsNotNone(task.region_cache)
        self.assertEqual(task.region_cache.cost_roi,(0,0,1000,200))
        calls.clear();task.run()
        self.assertTrue(all(calls))
