"""Host checks for horizontal-only column references and raw row reading."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import test_echo_probability_host as host
from test_echo_columns import compact_panel
from test_echo_probability_overlay import box, panel


class ColumnHostTests(unittest.TestCase):
    setUp = host.HostIntegrationTests.setUp

    def make_task(self, boxes=None):
        task=host.load_module('echo_score_task').EchoScoreOverlayTask()
        task.frame=SimpleNamespace(shape=(1440,2560,3))
        self.boxes=boxes if boxes is not None else compact_panel()
        self.calls=[]; self.drawn=[]; self.cleared=[]
        def ocr(frame=None,**bounds):
            self.calls.append((frame,bounds))
            if not bounds:return deepcopy(self.boxes)
            p=next(p for p in self.boxes[2::2] if abs(p.y-bounds['y']*1440)<.001)
            return [box(p.name.lstrip('+茶×'),2050,p.y,min(p.x+p.width-2050,220),p.height)]
        task.ocr=ocr
        overlay=SimpleNamespace(draw=lambda key,*a:self.drawn.append(key),clear_draw=self.cleared.append)
        task._ensure_overlay=lambda:overlay;task.get_overlay_view=lambda:overlay
        task._settings=lambda:{'角色评分模板':'清宵-通用','显示调谐概率':False}
        self.addCleanup(task.on_destroy)
        return task

    def test_500ms_polling_and_same_frame_name_crops_are_bounded(self):
        task=self.make_task();frame=task.frame;task.run()
        self.assertEqual(task.trigger_interval,.5)
        self.assertEqual(len(self.calls),8)
        self.assertTrue(all(f is frame for f,b in self.calls))
        self.assertEqual(len(task.painter.rectangles),7)

    def test_watermark_is_never_registered_and_old_key_is_cleared(self):
        task=self.make_task();task.run()
        self.assertNotIn('echo-score-status',self.drawn)
        self.assertIn('echo-score-status',self.cleared)

    def test_vertical_outlier_keeps_its_raw_y_and_does_not_move_other_rows(self):
        task=self.make_task();task.run();before=tuple(task.painter.rectangles)
        self.boxes[10].y+=11;self.boxes[11].y+=11;task.run()
        for i,(a,b) in enumerate(zip(before,task.painter.rectangles)):
            self.assertEqual((a.x,a.width),(b.x,b.width))
            self.assertEqual(a.y+(11 if i==4 else 0),b.y)

    def test_crop_exception_keeps_valid_current_rows_and_scores(self):
        task=self.make_task();task.run();before=tuple(task.painter.row_scores)
        self.boxes[11].name='8.6%'
        def ocr(frame=None,**bounds):
            if bounds:raise RuntimeError('synthetic OCR failure')
            return deepcopy(self.boxes)
        task.ocr=ocr;task.run()
        self.assertEqual(len(task.painter.row_scores),7)
        self.assertNotEqual(tuple(task.painter.row_scores),before)
        self.assertIn('当前评分',task.painter.summary)

    def test_page_loss_and_clear_discard_references(self):
        task=self.make_task();task.run();self.boxes=[];task.run()
        self.assertEqual(task.painter.summary,'')
        self.assertIsNone(task.layout_tracker.layout)

    def test_tuning_page_has_separate_x_references(self):
        task=self.make_task();task.run()
        self.boxes=panel();task.frame=SimpleNamespace(shape=(1000,1000,3))
        task.ocr=lambda frame=None,**kw:deepcopy(self.boxes)
        task.run()
        self.assertEqual(task.layout_tracker.key,('tuning',1000,1000))
        self.assertEqual(task.painter.rectangles[0].x,145)
        self.assertEqual(len(task.painter.rectangles),4)

    def test_no_default_diagnostic_writer_is_enabled(self):
        task=self.make_task()
        self.assertFalse(hasattr(task,'diagnostics'))
