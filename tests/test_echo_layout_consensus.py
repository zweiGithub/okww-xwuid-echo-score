"""Synthetic row geometry: consensus, current-frame reads and safe reacquisition."""
from copy import deepcopy
from statistics import median
from types import SimpleNamespace
import unittest

import test_echo_probability_host as host
from test_echo_probability_overlay import box, completed_panel


def aligned_panel(jitter=0, prefix=True):
    boxes = completed_panel()
    for index in range(7):
        prop, value = boxes[2 + 2*index:4 + 2*index]
        prop.y = value.y = (252 + index*40 if index < 2 else 332 + (index-2)*37) + jitter
        prop.height = value.height = 24
        name = prop.name
        contaminated = prefix and index in (0, 1, 2, 3, 5, 6)
        prop.name = ('茶' if index == 0 else '×' if index == 1 else '+') + name if contaminated else name
        prop.x = (1618 if contaminated else 1646) + jitter
        prop.width = len(name)*24 + (28 if contaminated else 0)
        value.width = len(value.name)*13
        value.x = 1970-value.width+jitter
    return boxes


def crop_results(boxes, bounds, width=2048, height=1152):
    result = []
    text_start=median(b.x+(28 if b.name[0] in '茶×+' else 0) for b in boxes[2::2])
    for index in range((len(boxes)-2)//2):
        prop, value = deepcopy(boxes[2+index*2:4+index*2])
        if bounds['y']*height <= prop.y+prop.height/2 <= bounds['to_y']*height:
            prop.name = prop.name.lstrip('茶×+')
            prop.x = text_start; prop.width = len(prop.name)*24
            result.extend((prop, value))
    return result


class ConsensusHostTests(unittest.TestCase):
    setUp = host.HostIntegrationTests.setUp

    def make_task(self, boxes):
        task=host.load_module('echo_score_task').EchoScoreOverlayTask()
        task.frame=SimpleNamespace(shape=(1152,2048,3))
        task.width=2048;task.height=1152
        self.boxes=boxes;self.calls=[];self.drawn=[];self.cleared=[]
        def ocr(frame=None, **bounds):
            self.calls.append((frame,bounds))
            return deepcopy(self.boxes) if not bounds else crop_results(self.boxes,bounds)
        task.ocr=ocr
        overlay=SimpleNamespace(draw=lambda key,*a:self.drawn.append(key),clear_draw=self.cleared.append)
        task._ensure_overlay=lambda:overlay; task.get_overlay_view=lambda:overlay
        task._settings=lambda:{'角色评分模板':'清宵-通用','显示调谐概率':False}
        self.addCleanup(task.on_destroy)
        return task

    def test_majority_defines_uniform_text_only_boxes_not_one_noisy_row(self):
        boxes=aligned_panel();boxes[10].x-=18; boxes[10].width+=18
        task=self.make_task(boxes);task.run()
        rects=task.painter.rectangles
        self.assertEqual(len(rects),7)
        self.assertEqual(len({r.x for r in rects}),1, 'Aligned rows must share the consensus text start')
        self.assertGreaterEqual(rects[0].x,1640,'Exclude the icon slot without cutting the first glyph')
        self.assertLessEqual(rects[0].x,1646)
        self.assertEqual(len({r.x+r.width for r in rects}),1)

    def test_small_jitter_holds_group_rois_and_boxes_but_refreshes_values(self):
        task=self.make_task(aligned_panel());task.run()
        before=tuple(task.painter.rectangles);before_scores=tuple(task.painter.row_scores)
        first_rois=[bounds for frame,bounds in self.calls if bounds]
        self.assertEqual(len(first_rois),2,'Read one stable main and one stable substat ROI')
        self.calls.clear();self.boxes=aligned_panel(jitter=2);self.boxes[7].name='8.6%'
        task.run()
        self.assertEqual(tuple(task.painter.rectangles),before)
        self.assertNotEqual(tuple(task.painter.row_scores),before_scores)
        self.assertEqual([bounds for frame,bounds in self.calls if bounds],first_rois)

    def test_watermark_is_never_registered_and_old_key_is_cleared(self):
        task=self.make_task(aligned_panel());task.run()
        self.assertNotIn('echo-score-status',self.drawn)
        self.assertIn('echo-score-status',self.cleared)

class ConsensusSafetyTests(unittest.TestCase):
    setUp = host.HostIntegrationTests.setUp
    make_task = ConsensusHostTests.make_task
    # Helpers are shared with the host tests; these exercise production outputs.
    def test_many_jittered_frames_keep_identical_geometry_and_fresh_scores(self):
        task=self.make_task(aligned_panel());task.run();baseline=tuple(task.painter.rectangles)
        for jitter in (-2,1,3,-1,0,2):
            self.boxes=aligned_panel(jitter=jitter)
            task.run()
            self.assertEqual(tuple(task.painter.rectangles),baseline)
            self.assertIn('当前评分：28.42',task.painter.summary)

    def test_missing_whole_row_clears_values_without_silently_unlocking_a_slot(self):
        task=self.make_task(aligned_panel());task.run()
        self.boxes=self.boxes[:-2]
        task.run()
        self.assertEqual(task.painter.row_scores,[])
        self.assertIn('行缺失',task.painter.summary)
        task.run()
        self.assertEqual(task.painter.row_scores,[])
        self.assertNotIn('当前评分',task.painter.summary)

    def test_missing_crop_rows_and_errors_never_reuse_previous_values(self):
        task=self.make_task(aligned_panel());task.run()
        full=self.boxes
        task.ocr=lambda frame=None,**bounds:deepcopy(full) if not bounds else []
        task.run()
        self.assertEqual(task.painter.row_scores,[])
        self.assertEqual(task.painter.rectangles,[])
        self.assertIn('识别暂不可用',task.painter.summary)

    def test_unknown_prefix_crop_must_verify_the_same_candidate(self):
        task=self.make_task(aligned_panel())
        def ocr(frame=None,**bounds):
            if not bounds:return deepcopy(self.boxes)
            result=crop_results(self.boxes,bounds)
            if result and result[0].name=='暴击伤害':result[0].name='暴击'
            return result
        task.ocr=ocr;task.run()
        self.assertEqual(task.painter.row_scores,[])
        self.assertIn('识别暂不可用',task.painter.summary)

    def test_movement_reacquires_instead_of_holding_old_roi(self):
        task=self.make_task(aligned_panel());task.run()
        before=tuple(task.painter.rectangles);first=[b for f,b in self.calls if b]
        self.boxes=aligned_panel(jitter=15);self.calls.clear()
        task.run()
        self.assertNotEqual(tuple(task.painter.rectangles),before)
        self.assertNotEqual([b for f,b in self.calls if b],first)
        self.assertIn('当前评分',task.painter.summary)

    def test_page_loss_clears_layout_and_allows_shorter_panel_reacquisition(self):
        task=self.make_task(aligned_panel());task.run()
        self.boxes=[];task.run()
        self.assertEqual(task.painter.summary,'')
        self.assertIsNone(task.layout_tracker.layout)
        self.boxes=aligned_panel()[:-2]
        task.ocr=lambda frame=None,**bounds:(deepcopy(self.boxes) if not bounds else
            [b for b in deepcopy(self.boxes) if bounds['y']*1152<=b.y+b.height/2<=bounds['to_y']*1152])
        task.run()
        self.assertNotIn('行缺失',task.painter.summary)

    def test_bad_column_evidence_shows_status_without_crop_or_stale_data(self):
        task=self.make_task(aligned_panel());task.run();self.calls.clear()
        self.boxes=aligned_panel()
        for i in range(7):self.boxes[2+i*2].x+=i*12
        task.run()
        self.assertEqual(task.painter.rectangles,[])
        self.assertIn('重新定位',task.painter.summary)
        self.assertEqual(len(self.calls),1)

    def test_clean_label_is_not_shifted_right_by_a_whole_glyph(self):
        task=self.make_task(aligned_panel(prefix=False));task.run()
        self.assertEqual(task.painter.rectangles[0].x,1643)

    def test_different_main_and_sub_spacing_are_preserved(self):
        task=self.make_task(aligned_panel());task.run()
        rects=task.painter.rectangles
        self.assertEqual(rects[1].y-rects[0].y,40)
        self.assertEqual([rects[i+1].y-rects[i].y for i in range(2,6)],[37]*4)

    def test_vertical_outlier_does_not_change_consensus_row_grid(self):
        task=self.make_task(aligned_panel());task.run();before=tuple(task.painter.rectangles)
        clean=aligned_panel();self.boxes=deepcopy(clean)
        self.boxes[10].y+=12;self.boxes[11].y+=12
        task.ocr=lambda frame=None,**bounds:deepcopy(self.boxes) if not bounds else crop_results(clean,bounds)
        task.run()
        self.assertEqual(tuple(task.painter.rectangles),before)
        self.assertIn('当前评分：28.42',task.painter.summary)

    def test_changed_echo_with_fewer_rows_uses_only_current_values(self):
        task=self.make_task(aligned_panel());task.run();self.boxes=aligned_panel()[:-2]
        self.boxes[7].name='8.6%'
        task.run()
        self.assertEqual(len(task.painter.rectangles),6)
        self.assertNotIn('行缺失',task.painter.summary)
        self.assertNotIn('当前评分：28.42',task.painter.summary)

    def test_resolution_change_scales_new_rois_without_old_pixel_geometry(self):
        task=self.make_task(aligned_panel());task.run();old=tuple(task.painter.rectangles)
        self.boxes=aligned_panel()
        for b in self.boxes:
            for attr in ('x','y','width','height'):setattr(b,attr,getattr(b,attr)/2)
        task.frame=SimpleNamespace(shape=(576,1024,3));self.calls.clear()
        def ocr(frame=None,**bounds):
            self.calls.append((frame,bounds))
            if not bounds:return deepcopy(self.boxes)
            result=[deepcopy(b) for b in self.boxes[2:] if bounds['y']*576<=b.y+b.height/2<=bounds['to_y']*576]
            for b in result:
                if b.name[0] in '茶×+':b.name=b.name[1:];b.x=823;b.width=len(b.name)*12
            return result
        task.ocr=ocr;task.run()
        self.assertEqual(len(task.painter.rectangles),7)
        self.assertLess(abs(task.painter.rectangles[0].x-old[0].x/2),3)
        self.assertEqual(len(self.calls),3)
        self.assertTrue(all(f is task.frame for f,b in self.calls))

    def test_switching_to_left_tuning_page_reacquires_separate_geometry(self):
        from test_echo_probability_overlay import panel
        task=self.make_task(aligned_panel());task.run()
        self.boxes=panel();task.frame=SimpleNamespace(shape=(1000,1000,3))
        task.ocr=lambda frame=None,**bounds:(deepcopy(self.boxes) if not bounds else
            [deepcopy(b) for b in self.boxes[2:] if bounds['y']*1000<=b.y+b.height/2<=bounds['to_y']*1000])
        task.run()
        self.assertEqual(len(task.painter.rectangles),4)
        self.assertEqual(task.painter.rectangles[0].x,147)
        self.assertEqual(task.layout_tracker.key,('tuning',1000,1000))

    def test_zero_substats_reads_only_main_roi_and_updates_probability(self):
        from test_echo_probability_overlay import panel
        task=self.make_task(panel(subs=()));task.frame=SimpleNamespace(shape=(1000,1000,3))
        calls=[]
        def ocr(frame=None,**bounds):
            calls.append(bounds)
            return deepcopy(self.boxes) if not bounds else deepcopy(self.boxes[2:])
        task.ocr=ocr;task.run()
        self.assertEqual(len(task.painter.rectangles),2)
        self.assertIn('当前评分',task.painter.summary)
        self.assertEqual(len(calls),2)

    def test_single_missing_value_clears_old_score(self):
        task=self.make_task(aligned_panel());task.run();del self.boxes[9]
        task.run()
        self.assertEqual(task.painter.row_scores,[])
        self.assertIn('未配对',task.painter.summary)

    def test_unexpected_crop_exception_is_a_status_not_old_score(self):
        task=self.make_task(aligned_panel());task.run()
        def ocr(frame=None,**bounds):
            if bounds:raise RuntimeError('synthetic OCR failure')
            return deepcopy(self.boxes)
        task.ocr=ocr;task.run()
        self.assertEqual(task.painter.row_scores,[])
        self.assertIn('识别失败',task.painter.summary)

    def test_valid_full_label_cannot_change_to_another_stat_in_crop(self):
        task=self.make_task(aligned_panel(prefix=False))
        def ocr(frame=None,**bounds):
            if not bounds:return deepcopy(self.boxes)
            result=crop_results(self.boxes,bounds)
            if result and result[0].name=='暴击伤害':result[0].name='暴击'
            return result
        task.ocr=ocr;task.run()
        self.assertEqual(task.painter.row_scores,[])
        self.assertIn('词条名称识别不完整',task.painter.summary)

    def test_motion_beyond_crop_padding_reacquires_before_any_glyph_is_clipped(self):
        task=self.make_task(aligned_panel());task.run();self.boxes=aligned_panel(jitter=-5)
        def ocr(frame=None,**bounds):
            if not bounds:return deepcopy(self.boxes)
            result=crop_results(self.boxes,bounds)
            if any(b.x < bounds['x']*2048 or b.x+b.width > bounds['to_x']*2048 for b in result):
                return []  # A real crop cannot return a glyph outside its pixels.
            return result
        task.ocr=ocr;task.run()
        self.assertIn('当前评分：28.42',task.painter.summary)
        self.assertLess(task.painter.rectangles[0].x,1643)

    def test_crop_failure_discards_bad_geometry_for_next_frame(self):
        task=self.make_task(aligned_panel());task.run()
        task.ocr=lambda frame=None,**bounds:deepcopy(self.boxes) if not bounds else []
        task.run()
        self.assertIsNone(task.layout_tracker.layout)

    def test_icon_prefixed_new_echo_with_zero_substats_is_not_a_missing_row(self):
        task=self.make_task(aligned_panel());task.run()
        self.boxes=aligned_panel()[:6];self.boxes[2].name='茶暴击';self.boxes[3].name='22.0%'
        task.run()
        self.assertEqual(len(task.painter.rectangles),2)
        self.assertIn('当前评分',task.painter.summary)
        self.assertNotIn('行缺失',task.painter.summary)

    def test_long_skill_labels_keep_tier_after_last_glyph(self):
        for name in ('共鸣技能伤害加成','共鸣解放伤害加成'):
            with self.subTest(name=name):
                boxes=aligned_panel(prefix=False);boxes[8].name=name;boxes[8].width=24*len(name)
                task=self.make_task(boxes);task.run()
                self.assertGreaterEqual(task.painter.rectangles[3].tier_x,1646+24*len(name)+4)
                self.assertTrue(task.painter.tier_labels[3])

    def test_tier_is_omitted_if_actual_text_value_gap_is_too_small(self):
        boxes=aligned_panel(prefix=False);boxes[8].name='共鸣技能伤害加成';boxes[8].width=192
        boxes[9].x=1850
        task=self.make_task(boxes);task.run()
        self.assertEqual(task.painter.tier_labels[3],'')

    def test_vertical_label_value_offset_is_inside_real_crop_pixels(self):
        for shift_all in (True,False):
            with self.subTest(shift_all=shift_all):
                task=self.make_task(aligned_panel(prefix=False));task.run()
                for b in self.boxes[2::2] if shift_all else self.boxes[2:3]:b.y-=5
                def ocr(frame=None,**bounds):
                    if not bounds:return deepcopy(self.boxes)
                    result=crop_results(self.boxes,bounds)
                    if any(b.y<bounds['y']*1152-.001 or b.y+b.height>bounds['to_y']*1152+.001 for b in result):
                        return []
                    return result
                task.ocr=ocr;task.run()
                self.assertIn('当前评分：28.42',task.painter.summary)
