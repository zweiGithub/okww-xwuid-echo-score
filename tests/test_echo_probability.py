import importlib
import itertools
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'echo-score'))
from echo_score import DEFAULT_TEMPLATE, SUBSTAT_TIERS, calculate_echo_score, TEMPLATE_OPTIONS


def row(name, value, text=None, **kwargs):
    return SimpleNamespace(stat_name=name, value=value,
                           value_text=text if text is not None else f'{value}{"" if name in {"攻击", "防御", "生命"} else "%"}',
                           recognition_valid=True, **kwargs)


MAIN = (row('暴击', 22), row('攻击', 150))
SUBS = (row('暴击', 6.3), row('暴击伤害', 12.6), row('攻击%', 6.4), row('攻击', 30), row('防御', 40))


class ProbabilityTests(unittest.TestCase):
    def setUp(self):
        try:
            self.p = importlib.import_module('echo_probability')
        except ModuleNotFoundError as error:
            self.fail(f'Missing probability implementation: {error}')

    def test_without_replacement_distribution_matches_exact_oracle(self):
        actual = dict(self.p.future_score_distribution((((0, .5), (100, .5)), ((0, .75), (100, .25)), ((0, 1.),)), 2))
        for score, expected in {0: 13/24, 100: 5/12, 200: 1/24}.items():
            self.assertAlmostEqual(actual[score], expected)
        self.assertEqual(set(actual), {0, 100, 200})

    def test_maximum_includes_tied_subsets(self):
        types = tuple(((0, 1-p), (100, p)) for p in (.5, .25, .75, 1.))
        dist = dict(self.p.future_score_distribution(types, 2))
        self.assertAlmostEqual(dist[200], 35/96)
        self.assertAlmostEqual(sum(score * prob for score, prob in dist.items()), 125)

    def test_zero_weights_and_no_remaining_slots_are_deterministic(self):
        self.assertEqual(self.p.future_score_distribution((((0, 1.),),)*4, 3), ((0, 1.),))
        self.assertEqual(self.p.future_score_distribution((((0, 1.),),)*4, 0), ((0, 1.),))

    def test_threshold_is_inclusive_and_does_not_round_user_target(self):
        dist = ((0, 13/24), (100, 5/12), (200, 1/24))
        self.assertAlmostEqual(self.p.probability_at_least(dist, 723, '8.23'), 11/24)
        self.assertAlmostEqual(self.p.probability_at_least(dist, 723, '8.230001'), 1/24)
        self.assertEqual(self.p.probability_at_least(dist, 723, 9.24), 0)
        self.assertEqual(self.p.probability_at_least(dist, 723, 7.23), 1)
        self.assertAlmostEqual(self.p.probability_at_least(dist, 723, '8.230000000000000000000000000001'), 1/24)

    def test_official_tiers_have_normalized_distinct_weights(self):
        p = self.p.tier_probabilities
        self.assertEqual(set(self.p.TIER_PERCENTAGES), set(SUBSTAT_TIERS))
        for name, values in SUBSTAT_TIERS.items():
            self.assertEqual(len(p(name)), len(values))
            self.assertAlmostEqual(math.fsum(p(name)), 1)
        self.assertAlmostEqual(p('暴击')[0], 23.3333/99.9999)
        self.assertAlmostEqual(p('攻击%')[0], 6.7961/99.9998)
        self.assertAlmostEqual(p('攻击')[0], .067961)
        self.assertAlmostEqual(p('防御')[0], .145631)
        self.assertNotEqual(p('暴击'), p('生命%'))

    def test_scores_match_existing_model_for_every_remaining_slot_count(self):
        for count in range(6):
            with self.subTest(count=count):
                subs = SUBS[:count]
                result = self.p.calculate_tuning_probability(DEFAULT_TEMPLATE, 4, MAIN, subs, 40)
                score = calculate_echo_score(DEFAULT_TEMPLATE, 4, '4C', MAIN, subs)
                self.assertEqual(result.current_score, score.current_score)
                self.assertEqual(result.potential_score, score.potential_score)
                self.assertEqual(result.remaining_slots, 5-count)
                self.assertLessEqual(result.current_score, result.expected_score)
                self.assertLessEqual(result.expected_score, result.potential_score + 1e-10)
                self.assertGreater(result.probability_at_potential, 0)
                self.assertLessEqual(result.probability_at_potential, 1)

    def test_expectation_matches_linearity_oracle_and_main_stat_not_excluded(self):
        from echo_score import _entry_weight, _selected_template, _truncate_2
        template = _selected_template(DEFAULT_TEMPLATE)
        subs = SUBS[:2]
        base = calculate_echo_score(DEFAULT_TEMPLATE, 4, '4C', MAIN, subs).current_score
        remaining = set(SUBSTAT_TIERS) - {r.stat_name for r in subs}
        expected_future = math.fsum(math.fsum(_truncate_2(v * _entry_weight(2, name, 4, template) / template['score_max'][2] * 50) * prob
                      for v, prob in zip(SUBSTAT_TIERS[name], self.p.tier_probabilities(name))) for name in remaining) * 3/len(remaining)
        result = self.p.calculate_tuning_probability(DEFAULT_TEMPLATE, 4, MAIN, subs, 40)
        self.assertAlmostEqual(result.expected_score, base + expected_future, places=10)
        self.assertIsNone(self.p.validate_tuning_input(DEFAULT_TEMPLATE, 4, MAIN, (), 40))

    def test_fully_tuned_target_and_ceiling_probabilities(self):
        score = calculate_echo_score(DEFAULT_TEMPLATE, 4, '4C', MAIN, SUBS).current_score
        result = self.p.calculate_tuning_probability(DEFAULT_TEMPLATE, 4, MAIN, SUBS, score)
        self.assertEqual(result.expected_score, score)
        self.assertEqual(result.probability_at_potential, 1)
        self.assertEqual(result.probability_at_target, 1)
        self.assertEqual(self.p.calculate_tuning_probability(DEFAULT_TEMPLATE, 4, MAIN, SUBS, score + .001).probability_at_target, 0)

    def test_invalid_inputs_do_not_produce_precise_probabilities(self):
        cases = [
            (4, MAIN, (row('未知词条', 6.3),), 40),
            (4, MAIN, (row('暴击', 6.3), row('暴击', 9.9)), 40),
            (4, MAIN[:1], (), 40),
            (4, MAIN, SUBS + (row('生命', 320),), 40),
            (4, MAIN, (row('暴击', 6.4),), 40),
            (4, MAIN, (row('暴击', float('nan')),), 40),
            (4, MAIN, (row('暴击', 6.3, '6.3'),), 40),
            (4, MAIN, (row('攻击', 30, '30%'),), 40),
            (4, (row('暴击', 23), MAIN[1]), (), 40),
            (3, MAIN, (), 40),
            (4, MAIN, (), float('inf')),
            (4, MAIN, (), -1),
        ]
        for cost, main, subs, target in cases:
            with self.subTest(cost=cost, main=main, subs=subs, target=target):
                self.assertIsNotNone(self.p.validate_tuning_input(DEFAULT_TEMPLATE, cost, main, subs, target))
                with self.assertRaises(self.p.TuningProbabilityError):
                    self.p.calculate_tuning_probability(DEFAULT_TEMPLATE, cost, main, subs, target)

    def test_valid_zero_weight_stat_is_accepted(self):
        self.assertIsNone(self.p.validate_tuning_input(DEFAULT_TEMPLATE, 4, MAIN, (row('防御', 40),), 40))

    def test_negative_and_nonfinite_template_weights_are_rejected(self):
        template = TEMPLATE_OPTIONS[DEFAULT_TEMPLATE][2]
        original = template['sub_props']['防御']
        try:
            for invalid in (-1, float('nan'), float('inf')):
                template['sub_props']['防御'] = invalid
                self.assertIsNotNone(self.p.validate_tuning_input(DEFAULT_TEMPLATE, 4, MAIN, (), 40))
        finally:
            template['sub_props']['防御'] = original

    def test_probability_format_does_not_hide_rare_nonzero_events(self):
        self.assertEqual(self.p.format_probability(0), '0%')
        self.assertEqual(self.p.format_probability(1), '100%')
        self.assertNotEqual(self.p.format_probability(1e-10), '0.00%')
        self.assertIn('e-', self.p.format_probability(1e-10))
        self.assertNotEqual(self.p.format_probability(.99999999), '100.00%')


if __name__ == '__main__':
    unittest.main()
