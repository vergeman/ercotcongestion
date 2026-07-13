"""Bootstrap 95% CI on west-hub Spearman rho per scenario.
    docker compose run --rm compute python \
       /compute/experiments/zonal_load/compare_zonal_lmp/west_bootstrap.py
"""
import numpy as np, pandas as pd
from scipy.stats import spearmanr

df = pd.read_csv('/compute/experiments/zonal_load/compare_zonal_lmp/lmp_compare_scenarios_sample.csv')
w = df[df.zone == 'west']
#w=df
rng = np.random.default_rng(0)
B = 5000

print(f"{'scenario':<16}  rho    95% CI         n")
for lab, g in w.groupby('scenario'):
    g = g.dropna(subset=['model_lmp', 'ercot_lmp'])
    a, b = g.model_lmp.values, g.ercot_lmp.values
    n = len(a)
    rho = spearmanr(a, b)[0]
    boots = []
    for _ in range(B):
        i = rng.integers(0, n, n)
        if len(np.unique(a[i])) > 1 and len(np.unique(b[i])) > 1:
            boots.append(spearmanr(a[i], b[i])[0])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"{lab:<16} {rho:+.2f}  [{lo:+.2f}, {hi:+.2f}]   {n}")
print("\nCI crossing 0 = rho not distinguishable from no correlation.")
