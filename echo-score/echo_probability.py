"""Conditional ordinary five-star tuning model (no OCR, GUI or host dependency).

Source: Kuro Korean probability disclosure, accessed 2026-10-02:
https://sdk-global.kurogames.com/pro/agreement/common/language_ko/product_info
Printed tier percentages are rounded; normalize each table independently.
Different rolls' tier draws are assumed independent. Regional equivalence is
not established by this disclosure. Reconstruction/locked rerolls are excluded.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
from functools import lru_cache
import math

from echo_score import (
    MAX_MAINSTAT_VALUES, SCORE_PER_ECHO, SUBSTAT_TIERS, TEMPLATE_OPTIONS,
    _entry_weight, _selected_template, _truncate_2, calculate_echo_score,
)

_CRIT_PERCENTAGES = (23.3333, 23.3333, 23.3333, 8., 8., 8., 3., 3.)
_COMMON_PERCENTAGES = (6.7961, 7.7670, 20.3883, 24.2718, 17.4757, 14.5631, 5.8252, 2.9126)
TIER_PERCENTAGES = {name: _COMMON_PERCENTAGES for name in SUBSTAT_TIERS}
TIER_PERCENTAGES.update({
    '暴击': _CRIT_PERCENTAGES,
    '暴击伤害': _CRIT_PERCENTAGES,
    '攻击': (6.7961, 52.4272, 37.8641, 2.9126),
    '防御': (14.5631, 44.6602, 32.0388, 8.7379),
})
_FLAT_STATS = {'攻击', '防御', '生命'}


class TuningProbabilityError(ValueError):
    """The recognized input cannot support the ordinary five-star model."""


@dataclass(frozen=True)
class TuningProbability:
    current_score: float
    potential_score: float
    expected_score: float
    probability_at_potential: float
    target_score: float
    probability_at_target: float
    remaining_slots: int


def tier_probabilities(stat_name):
    weights = TIER_PERCENTAGES[stat_name]
    total = math.fsum(weights)
    return tuple(weight / total for weight in weights)


def _valid_number(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def validate_target_score(value):
    """Return a settings-friendly error, accepting finite nonnegative targets."""
    if not _valid_number(value) or float(value) < 0:
        return '目标评分须为有限的非负数'
    return None


def validate_tuning_input(template_name, cost, main_rows, sub_rows, target_score):
    """Validate supplied rows, not rarity, level or unseen OCR completeness."""
    if error := validate_target_score(target_score):
        return error
    if template_name not in TEMPLATE_OPTIONS:
        return '评分模板无效'
    if isinstance(cost, bool) or cost not in MAX_MAINSTAT_VALUES:
        return 'COST 识别无效'
    if len(main_rows) != 2 or len(sub_rows) > 5:
        return '词条数量异常'
    names = [getattr(row, 'stat_name', '') for row in sub_rows]
    if len(set(names)) != len(names):
        return '副词条重复，请核对识别'
    for index, row in enumerate(tuple(main_rows) + tuple(sub_rows)):
        name, value = getattr(row, 'stat_name', ''), getattr(row, 'value', None)
        if not getattr(row, 'recognition_valid', True):
            return '词条名称识别不完整'
        if not _valid_number(value) or float(value) <= 0:
            return '词条数值识别异常'
        text = getattr(row, 'value_text', None)
        if text is not None and ('%' in text or '％' in text) == (name in _FLAT_STATS):
            return '词条百分号识别异常'
        if index < 2:
            maximum = MAX_MAINSTAT_VALUES[cost][index].get(name)
            if maximum is None or float(value) > maximum + 1e-9:
                return '主词条与 COST 不匹配'
        else:
            tiers = SUBSTAT_TIERS.get(name)
            if tiers is None:
                return '副词条类型无法识别'
            if not any(math.isclose(float(value), tier, rel_tol=0., abs_tol=1e-9) for tier in tiers):
                return '副词条数值不在五星档位中'
    template = _selected_template(template_name)
    try:
        maximum = template['score_max'][(1, 3, 4).index(cost)]
        weights = [_entry_weight(2, name, cost, template) for name in SUBSTAT_TIERS]
        weights += [_entry_weight(i, row.stat_name, cost, template) for i, row in enumerate(main_rows)]
        if not _valid_number(maximum) or float(maximum) <= 0 or any(not _valid_number(w) or w < 0 for w in weights):
            return '评分模板权重无效'
    except (KeyError, ValueError, TypeError, IndexError):
        return '评分模板权重无效'
    return None


@lru_cache(maxsize=128)
def future_score_distribution(type_distributions, remaining_slots):
    """Return (integer cents, probability) for k uniformly selected types.

    The coefficient of z**k in product_i(1 + z * PMF_i) sums all unordered
    k-subsets exactly once. Dividing by C(n,k) gives sampling without
    replacement. Equal-score tier outcomes are already combined by callers.
    No Monte Carlo, epsilon pruning, or 1-CDF subtraction is used.
    """
    count = len(type_distributions)
    if not 0 <= remaining_slots <= count:
        raise TuningProbabilityError('剩余词条数无效')
    if remaining_slots == 0:
        return ((0, 1.),)
    distributions = [{0: 1.}] + [{} for _ in range(remaining_slots)]
    for index, outcomes in enumerate(type_distributions):
        for chosen in range(min(remaining_slots, index + 1), 0, -1):
            current = distributions[chosen]
            previous = distributions[chosen - 1]
            for increment, probability in outcomes:
                if probability == 0:
                    continue
                for score, mass in previous.items():
                    new_score = score + increment
                    current[new_score] = current.get(new_score, 0.) + mass * probability
    divisor = math.comb(count, remaining_slots)
    result = tuple((score, mass / divisor) for score, mass in sorted(distributions[remaining_slots].items()))
    # Floating-point accumulation only; do not alter or remove rare tails.
    total = math.fsum(probability for _, probability in result)
    return tuple((score, probability / total) for score, probability in result)


def probability_at_least(distribution, base_cents, target_score):
    """Inclusive target, preserving sub-cent user thresholds without rounding."""
    try:
        target = Decimal(str(target_score))
        with localcontext() as context:
            context.prec = max(context.prec, len(target.as_tuple().digits) + 2)
            context.Emin = min(context.Emin, target.adjusted() - 2)
            threshold = int((target * 100).to_integral_value(rounding=ROUND_CEILING)) - base_cents
    except (InvalidOperation, ValueError, OverflowError) as error:
        raise TuningProbabilityError('目标评分无效') from error
    if threshold <= distribution[0][0]:
        return 1.
    return min(1., math.fsum(probability for score, probability in distribution if score >= threshold))


def calculate_tuning_probability(template_name, cost, main_rows, sub_rows, target_score):
    """Predict +25 final score conditional on these complete recognized rows."""
    if error := validate_tuning_input(template_name, cost, main_rows, sub_rows, target_score):
        raise TuningProbabilityError(error)
    score = calculate_echo_score(template_name, cost, '', main_rows, sub_rows)
    template = _selected_template(template_name)
    maximum = float(template['score_max'][(1, 3, 4).index(cost)])
    existing = {row.stat_name for row in sub_rows}
    type_distributions = []
    for name, tiers in SUBSTAT_TIERS.items():
        if name in existing:
            continue
        combined = defaultdict(float)
        weight = _entry_weight(2, name, cost, template)
        for value, probability in zip(tiers, tier_probabilities(name)):
            cents = round(_truncate_2(value * weight / maximum * SCORE_PER_ECHO) * 100)
            combined[cents] += probability
        type_distributions.append(tuple(sorted(combined.items())))
    remaining = 5 - len(sub_rows)
    distribution = future_score_distribution(tuple(type_distributions), remaining)
    base_cents = round(score.current_score * 100)
    potential_cents = base_cents + distribution[-1][0]
    return TuningProbability(
        current_score=score.current_score,
        potential_score=potential_cents / 100,
        expected_score=(base_cents + math.fsum(cents * probability for cents, probability in distribution)) / 100,
        probability_at_potential=distribution[-1][1],
        target_score=float(target_score),
        probability_at_target=probability_at_least(distribution, base_cents, target_score),
        remaining_slots=remaining,
    )


def format_probability(probability):
    """Keep tiny nonzero probabilities and near-certain events distinguishable."""
    if probability <= 0:
        return '0%'
    if probability >= 1:
        return '100%'
    percent = probability * 100
    if percent < .01:
        return f'{percent:.2e}%'
    if percent > 99.99:
        return '>99.99%'
    return f'{percent:.2f}%'
