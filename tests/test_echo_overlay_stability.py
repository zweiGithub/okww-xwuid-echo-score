"""Current-frame OCR repair and stable summary geometry; synthetic inputs only."""
import ctypes
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import test_echo_probability_host as host
from test_echo_probability_overlay import box, panel, completed_panel
from echo_stat_overlay import analyze_echo_stats, _paint_score_summary


class LabelCropTests(unittest.TestCase):
    def analyze(self, boxes, reader, width=2048, height=1152):
        return analyze_echo_stats(boxes, width, height, '清宵-通用', label_ocr=reader)

    def test_unknown_icon_requires_successful_current_crop_for_each_name(self):
        for index, raw, name in ((2, '茶暴击伤害', '暴击伤害'), (4, '×攻击', '攻击')):
            with self.subTest(raw=raw):
                boxes = completed_panel(); boxes[index].name = raw
                calls = []
                def reader(**bounds):
                    calls.append(bounds)
                    return [box(name, bounds['x']*2048+1, bounds['y']*1152+2, 80, 20)]
                result = self.analyze(boxes, reader)
                self.assertIn('期望终分：28.42', result.summary)
                self.assertEqual(len(calls), 1)
                self.assertEqual(boxes[index].name, raw, 'Do not mutate full-frame OCR boxes')
                bounds = calls[0]
                self.assertGreater(bounds['x']*2048, boxes[index].x+24)
                self.assertLess(bounds['x']*2048, boxes[index].x+38)
                self.assertLessEqual(bounds['to_x']*2048, boxes[index].x+boxes[index].width)
                self.assertLess(bounds['to_x']*2048, boxes[index+1].x)

    def test_failed_ambiguous_or_different_crop_never_accepts_guess(self):
        cases = ([], [box('茶暴击伤害',1645,252)], [box('暴击',1645,252)],
                 [box('暴击伤害',1645,252),box('攻击',1800,252)],
                 [box('+暴击伤害',1645,252)], [box('暴击伤害5档',1645,252)])
        for results in cases:
            with self.subTest(results=results):
                boxes=completed_panel(); boxes[2].name='茶暴击伤害'
                result=self.analyze(boxes,lambda **kw:results)
                self.assertIn('概率暂不可用',result.summary)
                self.assertNotIn('期望终分',result.summary)

    def test_crop_is_bounded_in_both_panel_layouts_and_uses_relative_coordinates(self):
        for boxes,w,h,index in ((completed_panel(),2048,1152,2),(panel(),1000,1000,2)):
            boxes[index].name='茶'+boxes[index].name
            candidate=boxes[index].name[1:]; calls=[]
            def reader(**bounds):
                calls.append(bounds)
                return [box(candidate,bounds['x']*w,bounds['y']*h)]
            result=self.analyze(boxes,reader,w,h)
            self.assertIn('期望终分',result.summary)
            self.assertEqual(len(calls),1)
            b=calls[0]
            self.assertEqual(set(b),{'x','y','to_x','to_y'})
            self.assertTrue(0<=b['x']<b['to_x']<=1)
            self.assertTrue(0<=b['y']<b['to_y']<=1)
            self.assertLessEqual(b['to_x']*w,boxes[index].x+boxes[index].width)
            self.assertLessEqual(b['to_x']*w,boxes[index+1].x)

    def test_only_single_prefix_full_labels_are_retried_and_budget_is_two(self):
        calls=[]
        def reader(**bounds): calls.append(bounds); return []
        for raw in ('暴击伤害', '+暴击伤害','暴击伤','茶茶暴击伤害','暴击伤害茶','暴击伤害3档','1暴击伤害'):
            boxes=completed_panel();boxes[2].name=raw
            self.analyze(boxes,reader)
        self.assertEqual(calls,[])
        boxes=completed_panel()
        for index in range(2,len(boxes),2): boxes[index].name='茶'+boxes[index].name
        self.analyze(boxes,reader)
        self.assertEqual(len(calls),2)

    def test_previous_success_is_not_used_for_later_bad_frame_or_settings(self):
        boxes=completed_panel();boxes[2].name='茶暴击伤害'
        good=self.analyze(boxes,lambda **kw:[box('暴击伤害',1645,252)])
        bad=self.analyze(boxes,lambda **kw:[])
        self.assertIn('期望终分',good.summary)
        self.assertNotIn('期望终分',bad.summary)
        self.assertIn('茶暴击伤害',bad.summary)

    def test_disabled_probability_and_non_echo_pages_do_not_retry(self):
        boxes=completed_panel();boxes[2].name='茶暴击伤害';calls=[]
        reader=lambda **kw:calls.append(kw) or []
        result=analyze_echo_stats(boxes,2048,1152,'清宵-通用',show_probability=False,label_ocr=reader)
        self.assertEqual(len(result.summary.splitlines()),3)
        result=analyze_echo_stats(boxes[1:],2048,1152,'清宵-通用',label_ocr=reader)
        self.assertEqual(result.summary,'')
        self.assertEqual(calls,[])

    def test_crop_exception_preserves_safe_diagnostic(self):
        boxes=completed_panel();boxes[2].name='茶暴击伤害'
        def failed(**kw): raise RuntimeError('OCR unavailable')
        result=self.analyze(boxes,failed)
        self.assertIn('概率暂不可用',result.summary)


class CurrentFrameHostTests(unittest.TestCase):
    setUp = host.HostIntegrationTests.setUp
    def test_no_frame_does_not_call_ocr_or_reuse_previous_summary(self):
        task=host.load_module('echo_score_task').EchoScoreOverlayTask()
        task.width=2048;task.height=1152;task.frame=None
        task.painter.summary='old result';calls=[]
        task.ocr=lambda **kw:calls.append(kw) or completed_panel()
        overlay=SimpleNamespace(draw=lambda *a:None,clear_draw=lambda *a:None)
        task._ensure_overlay=lambda:overlay;task.get_overlay_view=lambda:overlay
        task._settings=lambda:{}
        try:
            task.run()
            self.assertEqual(calls,[])
            self.assertEqual(task.painter.summary,'')
        finally:task.on_destroy()

    def test_retry_uses_exact_same_frame_and_host_ocr_keyword_signature(self):
        task=host.load_module('echo_score_task').EchoScoreOverlayTask()
        task.width=2048;task.height=1152;task.frame=SimpleNamespace(shape=(1152,2048,3))
        frame=task.frame;calls=[]
        boxes=completed_panel();boxes[2].name='茶暴击伤害'
        def ocr(x=0,y=0,to_x=1,to_y=1,match=None,width=0,height=0,box=None,name=None,
                threshold=0,frame=None,target_height=0,use_grayscale=False,log=False,
                screenshot=False,frame_processor=None,lib='default'):
            calls.append((frame,x,y,to_x,to_y))
            task.frame=SimpleNamespace(shape=(720,1280,3))  # A newer, resized frame arrives.
            task.width=1280;task.height=720
            if x==0:return boxes
            return [SimpleNamespace(name='暴击伤害',x=x*2048,y=y*1152,width=90,height=24)]
        task.ocr=ocr
        overlay=SimpleNamespace(draw=lambda *a:None,clear_draw=lambda *a:None)
        task._ensure_overlay=lambda:overlay;task.get_overlay_view=lambda:overlay
        task._settings=lambda:{'角色评分模板':'清宵-通用'}
        try:
            task.run()
            self.assertEqual(len(calls),2)
            self.assertTrue(all(call[0] is frame for call in calls))
            self.assertNotIn('词条名称识别不完整',task.painter.summary)
            self.assertTrue(.79 < calls[1][1] < .81, 'Crop uses captured frame dimensions')
        finally:task.on_destroy()


class SummaryLayoutTests(unittest.TestCase):
    def paint(self,text,with_colors=False):
        class Size(ctypes.Structure): _fields_=[('cx',ctypes.c_int),('cy',ctypes.c_int)]
        output=[];colors=[];current_color=[None]
        class Gdi:
            def __getattr__(self,name):return lambda *args:0
            def GetTextExtentPoint32W(self,hdc,text,n,p):
                p._obj.cx=sum(22 if ord(c)>255 else 11 for c in text);p._obj.cy=39
            def SetTextColor(self,hdc,color):current_color[0]=color
            def TextOutW(self,hdc,x,y,text,n):
                output.append((x,y,text));colors.append(current_color[0])
        native=ModuleType('ok.ui.overlay.win32_gdi');native.SIZE=Size;native.gdi32=Gdi();native._rgb=lambda *a:a
        stubs={n:ModuleType(n) for n in ('ok','ok.ui','ok.ui.overlay')};stubs['ok.ui.overlay'].win32_gdi=native
        with patch.dict(sys.modules,stubs),patch('echo_stat_overlay.os.name','nt'):
            _paint_score_summary(SimpleNamespace(hdc=0,ratio=1),SimpleNamespace(_frame_width=2048,_frame_height=1152),text)
        return (output[4::5],colors[4::5]) if with_colors else output[4::5]  # Skip halo draws.

    def test_anchor_does_not_depend_on_status_or_error_length(self):
        base='评分模板：清宵-通用\n当前评分：28.42\n理论最高：28.42\n五星普通估算 · 已识别5/5\n'
        tails=('概率计算中…\n核对完整词条；重构不适用',
               '期望终分：28.42\n达理论最高：100%\n目标≥40.00：0%\n核对完整词条；重构不适用',
               '概率暂不可用：词条名称识别不完整（主词条1：「茶暴击伤害」）',
               '概率暂不可用：词条名称识别不完整（主词条2：「×攻击」）')
        positions=[[(x,y) for x,y,t in self.paint(base+tail)[:4]] for tail in tails]
        self.assertTrue(all(p==positions[0] for p in positions[1:]),positions)

    def test_wrapping_preserves_semantic_summary_colors(self):
        text='评分模板：'+('长模板名称'*15)+'\n当前评分：28.42\n理论最高：28.42'
        lines,colors=self.paint(text,with_colors=True)
        for (_,_,line),color in zip(lines,colors):
            if line.startswith('当前评分'):
                self.assertEqual(color,(255,220,80))
            elif line.startswith('理论最高'):
                self.assertEqual(color,(120,235,150))
            else:
                self.assertEqual(color,(110,220,255))

    def test_long_diagnostic_is_bounded_away_from_stat_panel(self):
        text='评分模板：清宵-通用\n当前评分：28.42\n理论最高：28.42\n'+('错误'*300+'\n')*30
        lines=self.paint(text)
        self.assertLessEqual(len(lines),10)
        for x,y,line in lines:
            width=sum(22 if ord(c)>255 else 11 for c in line)
            self.assertGreaterEqual(x,0);self.assertLessEqual(x+width,2048*.755)
            self.assertGreaterEqual(y,0);self.assertLess(y+39,1152*.9)
        self.assertTrue(any('…' in line for _,_,line in lines))


if __name__=='__main__':unittest.main()
