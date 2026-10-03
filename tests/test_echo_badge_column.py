"""Independent badge columns follow current OCR rows, never old labels."""
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import test_echo_realtime as realtime
from test_echo_probability_overlay import panel, completed_panel
from echo_stat_overlay import analyze_echo_stats, EchoStatBoxPainter, StatRectangle


class BadgeColumnTests(unittest.TestCase):
    setUp = realtime.RealtimeTests.setUp
    make_task = realtime.RealtimeTests.make_task

    def set_rows(self, names, values):
        for i, (name, value) in enumerate(zip(names, values)):
            label, number = self.boxes[2+2*i:4+2*i]
            label.name, label.x, label.width = name, 1610, len(name)*28
            number.name = value

    def test_switching_label_lengths_and_order_updates_every_badge(self):
        task = self.make_task()
        self.set_rows(('暴击伤害','攻击','暴击','共鸣技能伤害加成','暴击伤害','重击伤害加成','防御'),
                      ('44.0%','150','6.3%','8.6%','12.6%','10.9%','40'))
        task.run(); anchors = tuple(task.painter.rectangles)
        self.assertEqual(task.painter.tier_labels[2:], ['1档','4档','1档','7档','1档'])
        self.set_rows(('导电伤害加成','攻击','暴击伤害','防御','共鸣效率','暴击','重击伤害加成'),
                      ('30.0%','100','12.6%','60','10.0%','8.1%','9.4%'))
        self.boxes[1].name = 'COST 3'
        task.frame = SimpleNamespace(shape=(1152,2048,3)); self.calls.clear(); task.run()
        self.assertEqual(task.painter.tier_labels[2:], ['1档','3档','5档','4档','5档'])
        self.assertEqual(self.calls, [{'frame':task.frame}])
        self.assertTrue(all(call['frame'] is task.frame for call in self.calls))
        self.assertIn('当前评分', task.painter.summary)
        self.assertEqual(len({r.tier_x for r in anchors[2:]}), 1)
        for r in anchors[2:]:
            self.assertLessEqual(r.tier_x + 2*r.tier_font_size, min(a.x for a in anchors)-4)

    def test_initial_long_name_cannot_disable_future_valid_badges(self):
        task = self.make_task()
        self.boxes[8].width = 280  # Former per-label placement has no space.
        task.run()
        self.assertEqual(task.painter.tier_labels[3], '3档')
        self.boxes[8].name = '防御'; self.boxes[8].width = 80; self.boxes[9].name = '60'
        task.run()
        self.assertEqual(task.painter.tier_labels[3], '3档')

    def test_clean_or_icon_inclusive_boxes_leave_the_icon_gutter_clear(self):
        for width in (320,640,1000,1280,2048,2560):
            positions=[]
            for clean in (False,True):
                boxes=completed_panel()
                if clean:
                    for b in boxes[2::2]:
                        end=b.x+b.width
                        b.x=1645;b.width=end-b.x
                scale=width/2048
                for b in boxes:
                    for key in ('x','y','width','height'):
                        setattr(b,key,getattr(b,key)*scale)
                result=analyze_echo_stats(boxes,width,1152*scale,'清宵-通用',show_probability=False)
                for r in result.rectangles[2:]:
                    self.assertLessEqual(r.tier_x+2*r.tier_font_size,1600*scale,(width,clean))
                positions.append(tuple(r.tier_x for r in result.rectangles[2:]))
            self.assertEqual(positions[0],positions[1])

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
