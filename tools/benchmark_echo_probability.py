#!/usr/bin/env python3
"""Reproducible cold/warm model benchmark; timings are not a Windows guarantee."""
import argparse
from collections import defaultdict
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'echo-score'))
from echo_probability import calculate_tuning_probability, future_score_distribution
from echo_score import DEFAULT_TEMPLATE, MAX_MAINSTAT_VALUES, SUBSTAT_TIERS, template_names


def row(name, value):
    percent = '' if name in {'攻击', '防御', '生命'} else '%'
    return SimpleNamespace(stat_name=name, value=value, value_text=f'{value}{percent}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-templates', action='store_true', help='Benchmark every shipped template and COST')
    args = parser.parse_args()
    names = template_names() if args.all_templates else [DEFAULT_TEMPLATE]
    cold, warm = defaultdict(list), defaultdict(list)
    rarest = 1.
    count = 0
    for name in names:
        for cost in (1, 3, 4):
            mains = tuple(row(*next(iter(slot.items()))) for slot in MAX_MAINSTAT_VALUES[cost])
            for remaining in range(6):
                subs = tuple(row(stat, tiers[0]) for stat, tiers in list(SUBSTAT_TIERS.items())[:5-remaining])
                future_score_distribution.cache_clear()
                start = time.perf_counter()
                result = calculate_tuning_probability(name, cost, mains, subs, 40)
                cold[remaining].append((time.perf_counter()-start)*1000)
                rarest = min(rarest, result.probability_at_potential)
                for _ in range(5):
                    start = time.perf_counter()
                    calculate_tuning_probability(name, cost, mains, subs, 40)
                    warm[remaining].append((time.perf_counter()-start)*1000)
                count += 1
    print(f'Python {sys.version.split()[0]}; {len(names)} templates; {count} cold cases; 3 COSTs')
    print('remaining  cold_median_ms  cold_max_ms  warm_median_ms  warm_max_ms')
    for remaining in range(6):
        print(f'{remaining:9d}  {statistics.median(cold[remaining]):14.3f}  {max(cold[remaining]):11.3f}'
              f'  {statistics.median(warm[remaining]):14.3f}  {max(warm[remaining]):11.3f}')
    print(f'Smallest observed ceiling probability: {rarest:.12g}')
    print('Production cold misses run on one background worker, not in paint/OCR tick.')


if __name__ == '__main__':
    main()
