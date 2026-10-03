"""Raw-label safeguards and summary geometry; synthetic inputs only."""
import ctypes
from types import ModuleType, SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import test_echo_probability_host as host
from test_echo_probability_overlay import box, panel, completed_panel
from echo_stat_overlay import analyze_echo_stats, _paint_score_summary


class RawLabelTests(unittest.TestCase):
    def test_unknown_or_multiple_prefixes_are_not_accepted_as_complete_names(self):
        for name in ('茶茶暴击','1暴击','暴击错误','暴击伤'):
            boxes=panel(((name,'6.3%'),))
            result=analyze_echo_stats(boxes,1000,1000,'清宵-通用',show_probability=True)
            self.assertNotIn('期望终分',result.summary)

    def test_non_echo_pages_are_ignored(self):
        result=analyze_echo_stats(completed_panel()[1:],2048,1152,'清宵-通用')
        self.assertEqual(result.summary,'')


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
