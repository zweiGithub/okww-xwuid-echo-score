"""Sanitized geometry patterns, not user diagnostic logs or screenshots."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from test_echo_probability_overlay import box
from echo_stat_overlay import analyze_echo_stats, _find_ocr_rows
from echo_layout import EchoLayoutTracker


def compact_panel():
    names = ('治疗效果加成', '攻击', '+生命', '重击伤害加成', '+攻击', '+共鸣技能伤害加成', '暴击伤害')
    values = ('26.4%', '150', '6.4%', '7.9%', '10.9%', '9.4%', '13.8%')
    # Icon-inclusive exact labels, 49 px main gap, and a separate substat numeric edge.
    labels = ((2010,312,216,37),(2010,357,110,45),(2015,405,107,45),
              (2050,458,176,34),(2012,500,108,45),(2020,551,262,34),(2050,596,122,37))
    numbers = ((2363,312,104,37),(2400,360,67,40),(2371,410,85,37),
               (2371,455,85,40),(2357,503,102,37),(2371,551,85,37),(2355,593,104,45))
    result=[box('声骸技能',2000,660),box('COST 4',2000,230)]
    for name,value,label,number in zip(names,values,labels,numbers):
        result += [box(name,*label),box(value,*number)]
    return result


def analyze(boxes, tracker=None, reader=None, width=2560, height=1440):
    return analyze_echo_stats(boxes,width,height,'清宵-通用',show_probability=False,
                              layout_tracker=tracker,label_ocr=reader)


class ColumnRegressionTests(unittest.TestCase):
    def test_close_rows_and_mixed_left_evidence_do_not_block_valid_raw_reading(self):
        boxes=compact_panel()
        result=analyze(boxes,EchoLayoutTracker())
        self.assertIn('当前评分',result.summary)
        self.assertEqual(len(result.rectangles),7)
        self.assertNotIn('重新定位',result.summary)

    def test_raw_bounds_widths_and_y_are_preserved_separately_from_display_columns(self):
        boxes=compact_panel(); before=deepcopy(boxes)
        result=analyze(boxes,EchoLayoutTracker())
        raw=_find_ocr_rows(boxes,2560*.76,2560*.99,1440*.18,1440*.47)
        self.assertEqual(result.raw_rows,tuple(raw))
        self.assertEqual([(r.y,r.height) for r in result.rectangles],[(r.y,r.height) for r in raw])
        self.assertEqual(boxes,before)

    def test_bad_horizontal_consensus_cannot_blank_current_values(self):
        boxes=compact_panel()
        for i,p in enumerate(boxes[2::2]):p.x+=i*8;p.width-=i*8
        result=analyze(boxes,EchoLayoutTracker())
        self.assertIn('当前评分',result.summary)
        self.assertEqual(len(result.row_scores),7)

    def test_horizontal_majority_holds_small_jitter_but_y_and_values_are_fresh(self):
        tracker=EchoLayoutTracker(); boxes=compact_panel()
        first=analyze(boxes,tracker)
        for b in boxes[2:]:b.x+=2;b.y+=5
        boxes[11].name='8.6%'
        second=analyze(boxes,tracker)
        self.assertEqual([(r.x,r.x+r.width) for r in first.rectangles],
                         [(r.x,r.x+r.width) for r in second.rectangles])
        self.assertEqual([r.y+5 for r in first.rectangles],[r.y for r in second.rectangles])
        self.assertNotEqual(first.row_scores,second.row_scores)

    def test_main_and_sub_numeric_edges_are_independent(self):
        result=analyze(compact_panel(),EchoLayoutTracker())
        rights=[r.x+r.width for r in result.rectangles]
        self.assertEqual(rights[:2],[2472]*2)
        self.assertEqual(rights[2:],[2461]*5)

    def test_large_x_movement_and_resolution_reacquire(self):
        tracker=EchoLayoutTracker(); boxes=compact_panel(); first=analyze(boxes,tracker)
        for b in boxes[2:]:b.x+=18
        moved=analyze(boxes,tracker)
        self.assertEqual(moved.rectangles[0].x,first.rectangles[0].x+18)
        for b in boxes:
            for key in ('x','y','width','height'):setattr(b,key,getattr(b,key)/2)
        resized=analyze(boxes,tracker,width=1280,height=720)
        self.assertEqual(tracker.key,('detail',1280,720))
        self.assertIn('当前评分',resized.summary)

    def test_one_x_outlier_does_not_shift_display_majority(self):
        boxes=compact_panel(); tracker=EchoLayoutTracker(); first=analyze(boxes,tracker)
        boxes[4].x-=30;boxes[4].width+=30
        second=analyze(boxes,tracker)
        self.assertEqual([(r.x,r.width) for r in first.rectangles],[(r.x,r.width) for r in second.rectangles])

    def test_zero_substats_and_unpaired_values_do_not_reuse_rows(self):
        tracker=EchoLayoutTracker(); boxes=compact_panel();analyze(boxes,tracker)
        short=analyze(boxes[:6],tracker)
        self.assertEqual(len(short.rectangles),2)
        self.assertEqual(len(short.row_scores),2)
        del boxes[9]
        bad=analyze(boxes,tracker)
        self.assertEqual(bad.row_scores,())
        self.assertIn('未配对',bad.summary)

    def test_name_crops_use_shared_text_start_and_each_raw_row_y_only(self):
        boxes=compact_panel();calls=[]
        def reader(**bounds):
            calls.append(bounds)
            row=next(p for p in boxes[2::2] if abs(p.y-bounds['y']*1440)<.001)
            name=row.name.lstrip('+')
            return [box(name,2050,row.y,min(row.x+row.width-2050,220),row.height)]
        result=analyze(boxes,EchoLayoutTracker(),reader)
        self.assertIn('当前评分',result.summary)
        self.assertEqual(len(calls),7)
        for b in calls:
            p=next(p for p in boxes[2::2] if abs(p.y-b['y']*1440)<.001)
            self.assertEqual(b['to_y']*1440,p.y+p.height)
            self.assertLessEqual(b['to_x']*2560,p.x+p.width+.001)
            self.assertGreaterEqual(b['x']*2560,2046)
            self.assertLessEqual(b['x']*2560,2050)
        self.assertEqual(len({r.x for r in result.rectangles}),1)
        self.assertGreaterEqual(result.rectangles[0].x,2045)

    def test_failed_crop_keeps_valid_raw_label_and_value(self):
        boxes=compact_panel(); baseline=analyze(boxes)
        result=analyze(boxes,EchoLayoutTracker(),lambda **kw:[])
        self.assertEqual(result.summary,baseline.summary)
        self.assertEqual(result.row_scores,baseline.row_scores)

    def test_different_exact_crop_label_cannot_change_original_stat(self):
        boxes=compact_panel();baseline=analyze(boxes)
        def reader(**bounds):
            p=next(p for p in boxes[2::2] if abs(p.y-bounds['y']*1440)<.001)
            return [box('暴击',2050,p.y,60,p.height)]
        result=analyze(boxes,EchoLayoutTracker(),reader)
        self.assertEqual(result.row_scores,baseline.row_scores)

    def test_unknown_prefix_requires_fresh_matching_crop_and_is_never_cached(self):
        boxes=compact_panel();boxes[2].name='暴击伤害';boxes[3].name='44.0%';boxes[4].name='茶攻击'
        def reader(**bounds):
            p=next(p for p in boxes[2::2] if abs(p.y-bounds['y']*1440)<.001)
            return [box(p.name.lstrip('+茶'),2050,p.y,min(p.x+p.width-2050,220),p.height)]
        tracker=EchoLayoutTracker()
        good=analyze_echo_stats(boxes,2560,1440,'清宵-通用',layout_tracker=tracker,label_ocr=reader)
        self.assertIn('期望终分',good.summary)
        bad=analyze_echo_stats(boxes,2560,1440,'清宵-通用',layout_tracker=tracker,label_ocr=lambda **kw:[])
        self.assertNotIn('期望终分',bad.summary)
        self.assertIn('词条名称识别不完整',bad.summary)

    def test_insufficient_anchor_evidence_does_not_guess_icon_width(self):
        boxes=compact_panel()[:6];calls=[]
        result=analyze(boxes,EchoLayoutTracker(),lambda **kw:calls.append(kw) or [])
        self.assertEqual(calls,[])
        self.assertIn('当前评分',result.summary)

    def test_page_loss_resets_geometry(self):
        tracker=EchoLayoutTracker();analyze(compact_panel(),tracker)
        result=analyze([],tracker)
        self.assertEqual(result.summary,'')
        self.assertIsNone(tracker.layout)

    def test_optional_crop_failure_cannot_make_column_edges_flicker(self):
        boxes=compact_panel();tracker=EchoLayoutTracker()
        def reader(**bounds):
            p=next(p for p in boxes[2::2] if abs(p.y-bounds['y']*1440)<.001)
            return [box(p.name.lstrip('+'),2050,p.y,min(p.x+p.width-2050,220),p.height)]
        good=analyze(boxes,tracker,reader)
        failed=analyze(boxes,tracker,lambda **kw:[])
        again=analyze(boxes,tracker,reader)
        edges=lambda a:[(r.x,r.x+r.width) for r in a.rectangles]
        self.assertEqual(edges(good),edges(failed))
        self.assertEqual(edges(good),edges(again))
        self.assertEqual(good.row_scores,failed.row_scores)

    def test_crop_anchor_does_not_depend_on_recognized_prefix_width(self):
        boxes=compact_panel();tracker=EchoLayoutTracker()
        first=analyze(boxes,tracker)
        boxes[4].name='×攻击'
        second=analyze(boxes,tracker)
        self.assertEqual(first.raw_rows[1].label_bounds,second.raw_rows[1].label_bounds)
        self.assertEqual(first.raw_rows[1].text_start,second.raw_rows[1].text_start)
        self.assertEqual(first.rectangles[1].x,second.rectangles[1].x)

    def test_out_of_crop_or_partial_label_results_never_verify_unknown_name(self):
        for kind in ('left','bottom','partial','extra','nan'):
            with self.subTest(kind=kind):
                boxes=compact_panel();boxes[2].name='暴击伤害';boxes[3].name='44.0%';boxes[4].name='茶攻击'
                def reader(**bounds):
                    p=next(p for p in boxes[2::2] if abs(p.y-bounds['y']*1440)<.001)
                    b=box(p.name.lstrip('+茶'),2050,p.y,min(p.x+p.width-2050,220),p.height)
                    if p is boxes[4]:
                        if kind=='left':b.x=bounds['x']*2560-3
                        if kind=='bottom':b.height+=5
                        if kind=='partial':b.name='攻'
                        if kind=='nan':b.x=float('nan')
                        if kind=='extra':return [b,box('攻击',2100,p.y,20,p.height)]
                    return [b]
                result=analyze_echo_stats(boxes,2560,1440,'清宵-通用',layout_tracker=EchoLayoutTracker(),label_ocr=reader)
                self.assertNotIn('期望终分',result.summary)
                self.assertIn('词条名称识别不完整',result.summary)

    def test_long_label_tier_is_after_text_or_hidden_when_no_gap(self):
        boxes=compact_panel()
        for label in ('共鸣技能伤害加成','共鸣解放伤害加成'):
            boxes[8].name=label;boxes[8].width=230
            result=analyze(boxes,EchoLayoutTracker())
            self.assertGreaterEqual(result.rectangles[3].tier_x,boxes[8].x+boxes[8].width+3)
            boxes[9].x=boxes[8].x+boxes[8].width+15
            crowded=analyze(boxes,EchoLayoutTracker())
            self.assertEqual(crowded.tier_labels[3],'')
            boxes[9].x=2371

    def test_validated_display_anchor_resets_after_real_horizontal_move(self):
        boxes=compact_panel();tracker=EchoLayoutTracker()
        def reader(**bounds):
            p=next(p for p in boxes[2::2] if abs(p.y-bounds['y']*1440)<.001)
            return [box(p.name.lstrip('+'),2050,p.y,min(p.x+p.width-2050,220),p.height)]
        analyze(boxes,tracker,reader)
        self.assertTrue(tracker.layout.text_validated)
        for b in boxes[2:]:b.x+=20
        analyze(boxes,tracker,lambda **kw:[])
        self.assertFalse(tracker.layout.text_validated)

    def test_validated_display_anchor_resets_on_page_loss_and_resolution(self):
        for mode in ('page','resolution'):
            with self.subTest(mode=mode):
                boxes=compact_panel();tracker=EchoLayoutTracker()
                def reader(**bounds):
                    p=next(p for p in boxes[2::2] if abs(p.y-bounds['y']*1440)<.001)
                    return [box(p.name.lstrip('+'),2050,p.y,min(p.x+p.width-2050,220),p.height)]
                analyze(boxes,tracker,reader)
                self.assertTrue(tracker.layout.text_validated)
                if mode=='page':
                    analyze([],tracker)
                    analyze(boxes,tracker,lambda **kw:[])
                else:
                    for b in boxes:
                        for key in ('x','y','width','height'):setattr(b,key,getattr(b,key)/2)
                    analyze(boxes,tracker,lambda **kw:[],width=1280,height=720)
                self.assertFalse(tracker.layout.text_validated)
