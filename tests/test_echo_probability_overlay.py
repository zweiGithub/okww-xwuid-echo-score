import unittest
from types import SimpleNamespace

from test_echo_probability import DEFAULT_TEMPLATE
from echo_stat_overlay import analyze_echo_stats, _find_ocr_rows
from echo_probability_service import TuningProbabilityService


def box(text, x, y, width=80, height=18):
    return SimpleNamespace(name=text, x=x, y=y, width=width, height=height)


def panel(subs=(('暴击', '6.3%'), ('防御', '40')), marker='声骸强化'):
    boxes = [box(marker, 10, 10), box('COST 4', 600, 50)]
    for index, (name, value) in enumerate((('暴击', '22%'), ('攻击', '150')) + tuple(subs)):
        boxes.extend((box(name, 150, 220 + index*30), box(value, 320, 220 + index*30, 60)))
    return boxes


def completed_panel(prefix=''):
    """A complete 4-cost panel; no private screenshot data is required."""
    labels = (('暴击伤害', '44.0%'), ('攻击', '150'), ('攻击', '7.9%'),
              ('普攻伤害加成', '7.9%'), ('暴击', '6.9%'),
              ('重击伤害加成', '8.6%'), ('共鸣效率', '8.4%'))
    boxes = [box('声骸技能', 1606, 530), box('COST 4', 1608, 205)]
    for index, (name, value) in enumerate(labels):
        boxes.extend((box(prefix + name, 1610, 252 + index * 38, 175, 24),
                      box(value, 1900, 252 + index * 38, 70, 24)))
    return boxes


class OverlayProbabilityTests(unittest.TestCase):
    def analyze(self, boxes, **kwargs):
        return analyze_echo_stats(boxes, 1000, 1000, DEFAULT_TEMPLATE, **kwargs)

    def test_probability_summary_exposes_conditional_scope_and_count(self):
        result = self.analyze(panel())
        self.assertIn('期望终分', result.summary)
        self.assertIn('达理论最高', result.summary)
        self.assertIn('目标≥40.00', result.summary)
        self.assertIn('五星普通', result.summary)
        self.assertIn('已识别2/5', result.summary)
        self.assertIn('核对完整词条', result.summary)
        self.assertIn('重构不适用', result.summary)

    def test_complete_panel_with_plain_labels_has_deterministic_probability(self):
        result = analyze_echo_stats(completed_panel(), 2048, 1152, '清宵-通用')
        self.assertIn('当前评分：28.42', result.summary)
        self.assertIn('期望终分：28.42', result.summary)
        self.assertIn('达理论最高：100%', result.summary)
        self.assertIn('目标≥40.00：0%', result.summary)

    def test_leading_icon_symbols_use_the_same_canonical_rows_as_scoring(self):
        plain = analyze_echo_stats(completed_panel(), 2048, 1152, '清宵-通用')
        for prefix in ('+', '＋', '✦', '✧', '★', '☆', '·', '•', ' + ✦ '):
            with self.subTest(prefix=prefix):
                result = analyze_echo_stats(completed_panel(prefix), 2048, 1152, '清宵-通用')
                self.assertEqual(result.summary, plain.summary)
                self.assertEqual(result.row_scores, plain.row_scores)

    def test_whitespace_normalization_preserves_traditional_label_support(self):
        result = self.analyze(panel(((' 重擊傷害加成 ', '7.9%'),)))
        self.assertIn('期望终分', result.summary)

    def test_existing_scoring_substring_matching_is_shared_without_trimming(self):
        for name in ('十暴击', 'x暴击', '1暴击', '暴击错误', '+暴击错误',
                     '暴击+', '暴击%', '暴击 1/8', '暴击伤'):
            with self.subTest(name=name):
                result = self.analyze(panel(((name, '6.3%'),)))
                plain = self.analyze(panel((('暴击', '6.3%'),)))
                self.assertEqual(result.summary, plain.summary)
                self.assertEqual(result.raw_rows[2].raw_stat_name, name)

    def test_recognized_row_retains_raw_ocr_label(self):
        rows = _find_ocr_rows(panel((('+暴击', '6.3%'),)), 90, 380, 200, 540)
        self.assertEqual(getattr(rows[2], 'raw_stat_name', None), '+暴击')
        self.assertEqual(rows[2].stat_name, '暴击')
        self.assertFalse(rows[2].recognition_valid)

    def test_unknown_canonical_name_uses_bounded_status_without_raw_text(self):
        raw_name = '伤害加成\n\x00\u202e' + '误' * 100
        for use_service in (False, True):
            with self.subTest(use_service=use_service):
                service = TuningProbabilityService() if use_service else None
                try:
                    result = self.analyze(panel(((raw_name, '6.3%'),)), probability_service=service)
                finally:
                    if service is not None:
                        service.close()
                line = result.summary.splitlines()[-1]
                self.assertEqual(line, '概率算不出来')
                self.assertNotIn('误', line)
                self.assertNotIn('\x00', result.summary)
                self.assertNotIn('\u202e', result.summary)
                self.assertEqual(len(result.summary.splitlines()), 4)
                self.assertLess(len(line), 65)

    def test_unknown_main_canonical_stat_remains_incompatible_with_cost(self):
        boxes = panel()
        boxes[2].name = '治疗效果错误'
        self.assertEqual(self.analyze(boxes).summary.splitlines()[-1], '概率算不出来')

    def test_disabled_probability_preserves_original_three_line_summary(self):
        result = self.analyze(panel(), show_probability=False)
        self.assertEqual(len(result.summary.splitlines()), 3)
        self.assertNotIn('期望终分', result.summary)

    def test_unknown_canonical_type_in_selected_rows_still_suppresses_probability(self):
        summary=self.analyze(panel((('伤害加成错误','6.3%'),))).summary
        self.assertIn('概率算不出来',summary)
        self.assertNotIn('期望终分',summary)

    def test_invalid_tier_duplicate_and_extra_rows_suppress_probability(self):
        cases = [panel((('暴击', '6.4%'),)), panel((('暴击', '6.3%'), ('暴击', '6.9%'))),
                 panel((('暴击', '6.3%'), ('防御', '40'), ('攻击', '30'), ('生命', '320'), ('共鸣效率', '6.8%'), ('攻击', '6.4%')))]
        for boxes in cases:
            with self.subTest(boxes=boxes):
                summary = self.analyze(boxes).summary
                self.assertIn('概率算不出来', summary)
                self.assertNotIn('期望终分', summary)

    def test_reconstruction_page_is_out_of_scope(self):
        result = self.analyze(panel(marker='声骸强化 声骸重构'))
        self.assertEqual(result.summary.splitlines()[-1], '概率算不出来')
        self.assertNotIn('期望终分', result.summary)

    def test_background_pending_and_error_states_do_not_show_stale_numbers(self):
        class Service:
            def __init__(self, status):
                self.status = status
            def request(self, *args):
                return SimpleNamespace(status=self.status, result=None, reason='测试错误')
        for status, text in [('pending', '概率计算中'), ('error', '概率算不出来')]:
            summary = self.analyze(panel(), probability_service=Service(status)).summary
            self.assertIn(text, summary)
            self.assertNotIn('期望终分', summary)

    def test_legacy_template_labels_upgrade_but_unknown_labels_stay_invalid(self):
        for name in ('通用', '今汐'):
            summary = analyze_echo_stats(panel(), 1000, 1000, name).summary
            self.assertIn('期望终分', summary)
        summary = analyze_echo_stats(panel(), 1000, 1000, '不存在的模板').summary
        self.assertEqual(summary.splitlines()[-1], '概率算不出来')
        self.assertNotIn('期望终分', summary)

    def test_oversized_ocr_number_does_not_crash_or_show_probabilities(self):
        summary = self.analyze(panel((('暴击', '9'*400 + '%'),))).summary
        self.assertIn('概率算不出来', summary)
        self.assertNotIn('期望终分', summary)

    def test_precise_text_target_keeps_same_threshold_in_label_and_calculation(self):
        summary = self.analyze(panel(), target_score='18.100000000000000001').summary
        self.assertIn('目标≥18.100000000000000001：', summary)

    def test_subcent_target_is_not_mislabelled_as_a_lower_threshold(self):
        summary = self.analyze(panel(), target_score=8.230001).summary
        self.assertIn('目标≥8.230001：', summary)

    def test_custom_target_is_used_without_50_point_clamp(self):
        result = self.analyze(panel(), target_score=100)
        self.assertIn('目标≥100.00：0%', result.summary)


if __name__ == '__main__':
    unittest.main()
