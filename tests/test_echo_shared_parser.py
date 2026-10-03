"""Scoring and probability consume the same canonical rows."""
from dataclasses import replace
import time
import unittest

from test_echo_probability_overlay import completed_panel, panel
from echo_stat_overlay import analyze_echo_stats, _find_ocr_rows
from echo_probability import calculate_tuning_probability, validate_tuning_input
from echo_probability_service import TuningProbabilityService


class SharedParserTests(unittest.TestCase):
    def test_prefix_noise_accepted_by_scoring_has_identical_probability(self):
        plain=analyze_echo_stats(completed_panel(),2048,1152,'清宵-通用')
        for prefix in ('＋','×','茶'):
            with self.subTest(prefix=prefix):
                boxes=completed_panel(prefix)
                result=analyze_echo_stats(boxes,2048,1152,'清宵-通用')
                self.assertEqual(result.row_scores,plain.row_scores)
                self.assertEqual(result.summary,plain.summary)
                self.assertTrue(all(r.raw_stat_name.startswith(prefix) for r in result.raw_rows))

    def test_raw_name_flag_cannot_override_known_canonical_scoring_input(self):
        rows=_find_ocr_rows(completed_panel(),2048*.76,2048*.99,1152*.18,1152*.47)
        noisy=[replace(r,recognition_valid=False,raw_stat_name='茶'+r.raw_stat_name) for r in rows]
        self.assertIsNone(validate_tuning_input('清宵-通用',4,noisy[:2],noisy[2:],40))
        self.assertEqual(calculate_tuning_probability('清宵-通用',4,noisy[:2],noisy[2:],40),
                         calculate_tuning_probability('清宵-通用',4,rows[:2],rows[2:],40))

    def test_service_reuses_same_canonical_input_regardless_of_raw_name_flag(self):
        rows=_find_ocr_rows(completed_panel(),2048*.76,2048*.99,1152*.18,1152*.47)
        noisy=[replace(r,recognition_valid=False,raw_stat_name='×'+r.raw_stat_name) for r in rows]
        calls=[]
        def calculate(*args):calls.append(args);return calculate_tuning_probability(*args)
        service=TuningProbabilityService(calculate)
        try:
            deadline=time.monotonic()+2
            state=service.request('清宵-通用',4,rows[:2],rows[2:],40)
            while state.status=='pending' and time.monotonic()<deadline:
                time.sleep(.001);state=service.request('清宵-通用',4,rows[:2],rows[2:],40)
            self.assertEqual(state.status,'ready')
            same=service.request('清宵-通用',4,noisy[:2],noisy[2:],40)
            self.assertEqual(same.status,'ready')
            self.assertEqual(same.result,state.result)
            self.assertEqual(len(calls),1)
        finally:service.close()

    def test_unknown_canonical_names_and_duplicate_canonical_stats_still_fail(self):
        rows=_find_ocr_rows(completed_panel(),2048*.76,2048*.99,1152*.18,1152*.47)
        unknown=replace(rows[2],stat_name='神秘属性',recognition_valid=False)
        self.assertIn('类型无法识别',validate_tuning_input('清宵-通用',4,rows[:2],[unknown],40))
        duplicate=analyze_echo_stats(panel((('暴击','6.3%'),('茶暴击','6.9%'))),1000,1000,'清宵-通用')
        self.assertIn('副词条重复',duplicate.summary)
        self.assertNotIn('期望终分',duplicate.summary)
