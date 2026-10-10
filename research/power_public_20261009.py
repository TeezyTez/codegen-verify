"""Outcome-blind approximate power, paired family means; standard library only."""
import argparse
import json
import math
import random
from pathlib import Path
from statistics import NormalDist


def simulate(n, draws=5000):
    rng = random.Random(20261009)
    z = NormalDist().inv_cdf(1 - .025 / 2)
    rows = []
    for q in (.1, .2, .4):
        for rho in (0, .5, 1):
            positive = 0
            for _ in range(draws):
                total = square = 0.
                for _ in range(n):
                    def sample():
                        u = rng.random()
                        return 1 if u < (q + .05) / 2 else -1 if u < q else 0
                    value = sample() if rng.random() < rho else sum(sample() for _ in range(3)) / 3
                    total += value
                    square += value * value
                mean = total / n
                se = math.sqrt(max(0., (square - total * total / n) / (n - 1) / n))
                positive += mean - z * se > 0
            rows.append({'per_repeat_discordance_q': q, 'within_family_correlation': rho,
                         'true_difference': .05, 'positive_lower_bound_frequency': positive / draws})
    return {'families': n, 'repetitions': 3, 'simulation_draws': draws, 'seed': 20261009,
            'contrast_confidence_level': .975, 'rows': rows,
            'method': 'Paired categorical differences {-1,0,+1}; repeated differences shared with probability rho, otherwise independent; normal/Wald approximation to family-mean uncertainty.',
            'limitations': ['Planning simulation, not observed evidence or exact power of the final bootstrap procedure.',
                           'Development trials do not identify plausible discordance/correlation; fixed sensitivity grid used.',
                           'N is all eligible held-out representatives, not chosen by observed significance.']}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--families', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.families < 2 or a.output.exists():
        raise ValueError('fresh output and at least two families required')
    result = simulate(a.families)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result))
