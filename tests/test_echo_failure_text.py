"""Failure wording is short; validation and valid/pending results stay intact."""
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from test_echo_probability_overlay import panel, completed_panel, box
import test_echo_realtime as realtime
from echo_stat_overlay import analyze_echo_stats, _find_ocr_rows


class ProbabilityFailureTextTests(unittest.TestCase):
    def test_unused_unpaired_fragments_do_not_leak_or_block_paired_rows(self):
        boxes=panel();boxes=[b for b in boxes if b.name!='6.3%']
        rows,reason=_find_ocr_rows(boxes,90,380,200,540,with_diagnostics=True)
        self.assertEqual(reason,'存在未配对的名称或数值')
        result=analyze_echo_stats(boxes,1000,1000,'清宵-通用')
        expected=analyze_echo_stats(panel((('防御','40'),)),1000,1000,'清宵-通用')
        self.assertEqual(result.summary,expected.summary)
        self.assertEqual(result.row_scores,expected.row_scores)

    def test_stray_label_or_value_keeps_same_scoring_rows_and_probability(self):
        for complete in (False,True):
            boxes=completed_panel() if complete else panel()
            width,height=(2048,1152) if complete else (1000,1000)
            plain=analyze_echo_stats(boxes,width,height,'清宵-通用')
            for text in ('攻击','10.9%'):
                extra=box(text,1650 if complete else 200,530 if complete else 500)
                result=analyze_echo_stats(boxes+[extra],width,height,'清宵-通用')
                self.assertEqual(result.row_scores,plain.row_scores)
                self.assertEqual(result.summary,plain.summary)
                self.assertEqual([(r.stat_name,r.value) for r in result.read_rows],
                                 [(r.stat_name,r.value) for r in plain.read_rows])

    def test_excessive_paired_slots_and_reconstruction_still_do_not_calculate(self):
        cases=(panel((('暴击','6.3%'),('防御','40'),('攻击','30'),('生命','320'),
                      ('共鸣效率','6.8%'),('攻击','6.4%'))),
               panel(marker='声骸强化 声骸重构'))
        for boxes in cases:
            with patch('echo_stat_overlay.calculate_tuning_probability') as calculate:
                result=analyze_echo_stats(boxes,1000,1000,'清宵-通用')
            calculate.assert_not_called()
            self.assertEqual(result.summary.splitlines()[-1],'概率算不出来')

    def test_invalid_model_inputs_keep_validation_but_hide_internal_reasons(self):
        cases=(panel((('伤害加成错误','6.3%'),)),panel((('暴击','6.4%'),)),
               panel((('暴击','6.3'),)),panel((('暴击','6.3%'),('茶暴击','6.9%'))),
               panel(marker='声骸强化 声骸重构'))
        for boxes in cases:
            with self.subTest(boxes=boxes):
                result=analyze_echo_stats(boxes,1000,1000,'清宵-通用')
                self.assertEqual(result.summary.splitlines()[3:],['概率算不出来'])
                self.assertNotIn('期望终分',result.summary)

    def test_service_failure_is_short_and_pending_is_not_failure(self):
        for status in ('invalid','error','closed','pending'):
            service=SimpleNamespace(request=lambda *a:SimpleNamespace(status=status,reason='internal detail',result=None))
            result=analyze_echo_stats(panel(),1000,1000,'清宵-通用',probability_service=service)
            self.assertNotIn('internal detail',result.summary)
            if status=='pending':
                self.assertIn('概率计算中…',result.summary)
                self.assertNotIn('概率算不出来',result.summary)
            else:self.assertEqual(result.summary.splitlines()[3:],['概率算不出来'])

    def test_score_failure_cannot_leak_details_into_probability_display(self):
        for outcome in ('exception','none'):
            kwargs={'side_effect':ValueError('internal')} if outcome=='exception' else {'return_value':None}
            with patch('echo_stat_overlay.calculate_echo_score',**kwargs):
                result=analyze_echo_stats(panel(),1000,1000,'清宵-通用')
            self.assertEqual(result.summary,'概率算不出来')

    def test_success_and_probability_disabled_display_are_unchanged(self):
        result=analyze_echo_stats(completed_panel(),2048,1152,'清宵-通用')
        self.assertIn('期望终分：28.42',result.summary)
        self.assertIn('达理论最高：100%',result.summary)
        off=analyze_echo_stats(completed_panel(),2048,1152,'清宵-通用',show_probability=False)
        self.assertEqual(off.summary,'评分模板：清宵-通用\n当前评分：28.42\n理论最高：28.42')


class HostFailureTextTests(unittest.TestCase):
    setUp=realtime.RealtimeTests.setUp
    make_task=realtime.RealtimeTests.make_task

    def test_host_read_failure_uses_short_probability_message(self):
        task=self.make_task();self.settings['显示调谐概率']=True
        def fail(**kwargs):self.calls.append(kwargs);raise RuntimeError('internal')
        task.ocr=fail;task.run()
        self.assertEqual(self.calls,[{'frame':task.frame}])
        self.assertEqual(task.painter.summary,'概率算不出来')
