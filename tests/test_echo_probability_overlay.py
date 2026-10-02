import unittest
from types import SimpleNamespace

from test_echo_probability import DEFAULT_TEMPLATE
from echo_stat_overlay import analyze_echo_stats, _find_ocr_rows


def box(text, x, y, width=80, height=18):
    return SimpleNamespace(name=text, x=x, y=y, width=width, height=height)


def panel(subs=(('暴击', '6.3%'), ('防御', '40')), marker='声骸强化'):
    boxes = [box(marker, 10, 10), box('COST 4', 600, 50)]
    for index, (name, value) in enumerate((('暴击', '22%'), ('攻击', '150')) + tuple(subs)):
        boxes.extend((box(name, 150, 220 + index*30), box(value, 320, 220 + index*30, 60)))
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

    def test_disabled_probability_preserves_original_three_line_summary(self):
        result = self.analyze(panel(), show_probability=False)
        self.assertEqual(len(result.summary.splitlines()), 3)
        self.assertNotIn('期望终分', result.summary)

    def test_missing_or_unknown_ocr_rows_suppress_probability(self):
        unknown = panel((('神秘属性', '6.3%'),))
        missing = panel()
        missing = [b for b in missing if not (b.name == '6.3%')]
        unknown_similar = panel((('暴击错误', '6.3%'),))
        for boxes in (unknown, missing, unknown_similar):
            with self.subTest(boxes=boxes):
                summary = self.analyze(boxes).summary
                self.assertIn('概率暂不可用', summary)
                self.assertNotIn('期望终分', summary)

    def test_invalid_tier_duplicate_and_extra_rows_suppress_probability(self):
        cases = [panel((('暴击', '6.4%'),)), panel((('暴击', '6.3%'), ('暴击', '6.9%'))),
                 panel((('暴击', '6.3%'), ('防御', '40'), ('攻击', '30'), ('生命', '320'), ('共鸣效率', '6.8%'), ('攻击', '6.4%')))]
        for boxes in cases:
            with self.subTest(boxes=boxes):
                summary = self.analyze(boxes).summary
                self.assertIn('概率暂不可用', summary)
                self.assertNotIn('期望终分', summary)

    def test_reconstruction_page_is_out_of_scope(self):
        result = self.analyze(panel(marker='声骸强化 声骸重构'))
        self.assertIn('重构', result.summary)
        self.assertNotIn('期望终分', result.summary)

    def test_background_pending_and_error_states_do_not_show_stale_numbers(self):
        class Service:
            def __init__(self, status):
                self.status = status
            def request(self, *args):
                return SimpleNamespace(status=self.status, result=None, reason='测试错误')
        for status, text in [('pending', '概率计算中'), ('error', '概率暂不可用')]:
            summary = self.analyze(panel(), probability_service=Service(status)).summary
            self.assertIn(text, summary)
            self.assertNotIn('期望终分', summary)

    def test_legacy_template_labels_upgrade_but_unknown_labels_stay_invalid(self):
        for name in ('通用', '今汐'):
            summary = analyze_echo_stats(panel(), 1000, 1000, name).summary
            self.assertIn('期望终分', summary)
        summary = analyze_echo_stats(panel(), 1000, 1000, '不存在的模板').summary
        self.assertIn('评分模板无效', summary)
        self.assertNotIn('期望终分', summary)

    def test_oversized_ocr_number_does_not_crash_or_show_probabilities(self):
        summary = self.analyze(panel((('暴击', '9'*400 + '%'),))).summary
        self.assertIn('概率暂不可用', summary)
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
