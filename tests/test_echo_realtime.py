"""One current full-frame read per 1000ms configured tick; no OCR state."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import test_echo_probability_host as host
from test_echo_probability_overlay import completed_panel, panel
from echo_stat_overlay import _find_ocr_rows, analyze_echo_stats


class RealtimeTests(unittest.TestCase):
    setUp = host.HostIntegrationTests.setUp

    def make_task(self):
        self.task_module=host.load_module('echo_score_task')
        task=self.task_module.EchoScoreOverlayTask()
        self.boxes=completed_panel();self.calls=[]
        self.settings={'角色评分模板':'清宵-通用','显示调谐概率':False}
        task.frame=SimpleNamespace(shape=(1152,2048,3))
        def ocr(**kwargs):
            self.calls.append(kwargs)
            return deepcopy(self.boxes)
        task.ocr=ocr
        self.drawn=[];self.cleared=[]
        overlay=SimpleNamespace(draw=lambda key,*a:self.drawn.append(key),clear_draw=self.cleared.append)
        task._ensure_overlay=lambda:overlay;task.get_overlay_view=lambda:overlay
        task._settings=lambda:self.settings
        self.addCleanup(task.on_destroy)
        return task

    def test_one_full_frame_read_on_every_enabled_tick(self):
        task=self.make_task()
        self.assertEqual(task.trigger_interval,1.0)
        for _ in range(3):
            task.frame=SimpleNamespace(shape=(1152,2048,3));self.calls.clear();task.run()
            self.assertEqual(self.calls,[{'frame':task.frame}])
        self.assertFalse(hasattr(task,'region_cache'))
        self.assertFalse(hasattr(task,'layout_tracker'))

    def test_current_geometry_values_and_tiers_replace_previous_frame(self):
        task=self.make_task();task.run()
        old=tuple(task.painter.rectangles);old_scores=tuple(task.painter.row_scores)
        self.boxes[7].name='11.6%'
        for b in self.boxes[2:]:b.x+=3;b.y+=4
        self.calls.clear();task.run()
        self.assertEqual(self.calls,[{'frame':task.frame}])
        self.assertEqual([(r.x,r.y,r.width,r.height) for r in task.painter.rectangles],
                         [(r.x+3,r.y+4,r.width,r.height) for r in old])
        self.assertNotEqual(tuple(task.painter.row_scores),old_scores)
        self.assertEqual(task.painter.tier_labels[2],'8档')
        self.assertEqual(task.painter.tier_colors[2],(255,75,75))

    def test_uses_captured_frame_dimensions_when_new_frame_arrives_during_ocr(self):
        task=self.make_task();frame=task.frame
        def ocr(**kwargs):
            self.calls.append(kwargs);task.frame=SimpleNamespace(shape=(720,1280,3))
            return self.boxes
        task.ocr=ocr;task.run()
        self.assertEqual(self.calls,[{'frame':frame}])
        self.assertEqual(len(task.painter.rectangles),7)

    def test_unknown_icon_prefix_is_not_trimmed_or_cropped(self):
        task=self.make_task();self.boxes[6].name='+攻击';task.run()
        self.assertEqual(self.calls,[{'frame':task.frame}])
        rows=_find_ocr_rows(self.boxes,2048*.76,2048*.99,1152*.18,1152*.47)
        self.assertEqual(rows[2].raw_stat_name,'+攻击')
        self.assertFalse(rows[2].recognition_valid)
        result=analyze_echo_stats(self.boxes,2048,1152,'清宵-通用')
        self.assertIn('名称识别不完整',result.summary)
        self.assertNotIn('期望终分',result.summary)

    def test_disabled_or_no_frame_clears_without_ocr(self):
        task=self.make_task();task.run();self.calls.clear()
        self.settings['启用声骸评分']=False;task.run()
        self.assertEqual(self.calls,[]);self.assertEqual(task.painter.rectangles,[])
        self.settings['启用声骸评分']=True;task.run();self.calls.clear()
        task.frame=None;task.run()
        self.assertEqual(self.calls,[]);self.assertEqual(task.painter.tier_labels,[])
        self.assertEqual(task.painter.row_scores,[])

    def test_empty_failed_or_other_page_read_never_keeps_old_content(self):
        for mode in ('empty','exception','other_page','missing_value'):
            with self.subTest(mode=mode):
                task=self.make_task();task.run();self.calls.clear()
                if mode=='empty':self.boxes=[]
                elif mode=='other_page':self.boxes[0].name='其他界面'
                elif mode=='missing_value':self.boxes.pop(7)
                else:
                    def fail(**kwargs):self.calls.append(kwargs);raise RuntimeError('OCR')
                    task.ocr=fail
                task.run()
                self.assertEqual(self.calls,[{'frame':task.frame}])
                self.assertEqual(task.painter.rectangles,[])
                self.assertEqual(task.painter.row_scores,[])
                self.assertEqual(task.painter.tier_labels,[])

    def test_zero_substats_and_new_rows_are_read_fresh(self):
        task=self.make_task();self.boxes=panel(subs=())
        task.frame=SimpleNamespace(shape=(1000,1000,3));task.run()
        self.assertEqual(len(task.painter.rectangles),2)
        self.boxes=panel();self.calls.clear();task.run()
        self.assertEqual(self.calls,[{'frame':task.frame}])
        self.assertEqual(len(task.painter.rectangles),4)
        self.assertEqual(task.painter.tier_labels[2:],['1档','1档'])

    def test_raw_boxes_are_not_aligned_or_trimmed(self):
        boxes=completed_panel();boxes[6].x-=13;before=deepcopy(boxes)
        result=analyze_echo_stats(boxes,2048,1152,'清宵-通用',show_probability=False)
        raw=_find_ocr_rows(boxes,2048*.76,2048*.99,1152*.18,1152*.47)
        self.assertEqual([(r.x,r.y,r.width,r.height) for r in result.rectangles],
                         [(r.x,r.y,r.width,r.height) for r in raw])
        self.assertEqual(boxes,before)

    def test_resolution_change_uses_current_dimensions_and_raw_positions(self):
        task=self.make_task();task.run();self.calls.clear()
        for b in self.boxes:
            for key in ('x','y','width','height'):setattr(b,key,getattr(b,key)/2)
        task.frame=SimpleNamespace(shape=(576,1024,3));task.run()
        self.assertEqual(self.calls,[{'frame':task.frame}])
        self.assertEqual(len(task.painter.rectangles),7)
        self.assertEqual(task.painter.rectangles[0].x,round(self.boxes[2].x-5))

    def test_hidden_window_and_disposal_clear_display(self):
        task=self.make_task();task.run();self.calls.clear()
        self.task_module.og=SimpleNamespace(device_manager=SimpleNamespace(
            hwnd_window=SimpleNamespace(exists=True,visible=False)))
        task.run()
        self.assertEqual(self.calls,[])
        self.assertEqual(task.painter.summary,'')
        task.get_overlay_view=lambda:None;task.on_destroy()
        self.assertEqual(task.painter.rectangles,[])
        self.assertTrue(task.probability_service._closed)

    def test_watermark_and_default_diagnostics_remain_absent(self):
        task=self.make_task();task.run()
        self.assertNotIn('echo-score-status',self.drawn)
        self.assertIn('echo-score-status',self.cleared)
        self.assertFalse(hasattr(task,'diagnostics'))
