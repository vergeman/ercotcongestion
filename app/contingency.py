#
# Top N-1 Contingency
# If any single line were to trip, which trip would cause the most stress?
#
# flow_post[line] = flow_base[line] + LODF[line, c] × flow_base[c]
#

import numpy as np
import pandas as pd


def compute_contingencies(n, lodf_full, top_k, radial_threshold: float = 5.0) -> pd.DataFrame:

    # We only simulate line outages, not transformer outages
    # (transformers are usually protected differently and we don't trip them for N-1)
    n_lines_n = len(n.lines)
    lodf_line_line = lodf_full[:n_lines_n, :n_lines_n]  # line outages affect lines only

    # Base flows on lines
    flow_base = n.lines_t.p0.iloc[0].reindex(n.lines.index).fillna(0).values
    s_nom = n.lines['s_nom'].values

    # Skip near-radial lines whose LODF columns blow up; they lack alternate
    # paths and can yield isolated grid islands - likely unrealistic. Generates
    # huge stress numbers and collapse, so assume this is a math artifact not
    # an overload pattern and filter out w/ simple threshold filter for now.
    col_max = np.abs(lodf_line_line).max(axis=0)
    radial_mask = (col_max > radial_threshold) | np.isnan(col_max)

    # Rank all line outages by stress
    stress_scores = []
    for i, line in enumerate(n.lines.index):
        if radial_mask[i]:
            continue
        score, _ = _contingency_stress(i, lodf_line_line, flow_base, s_nom)
        stress_scores.append((line, score))

    stress_df = pd.DataFrame(stress_scores, columns=['line', 'stress']).set_index('line')
    stress_df = stress_df.sort_values('stress', ascending=False).head(top_k)
    return stress_df


# For each candidate line outage, compute post-outage stress metric
def _contingency_stress(outage_idx, lodf_line_line, flow_base, s_nom):
    """Return post-outage stress (sum of overloads) when line at outage_idx trips."""

    # Post-outage flows on all lines
    shift = lodf_line_line[:, outage_idx] * flow_base[outage_idx]
    flow_post = flow_base + shift
    flow_post[outage_idx] = 0.0  # tripped line carries no flow

    # Loading ratio for each line under the outage
    loading = np.abs(flow_post) / s_nom

    # Overload: how much each line exceeds its limit (0 if under)
    overload = np.maximum(loading - 1.0, 0.0)

    # Stress score: sum of overload percentages (could weight by MW instead)
    return overload.sum(), overload



def contingency_diagnostics(n, stress_df, lodf_full):
    if stress_df.empty:
        print("No contingencies to evaluate.")
        return

    print(f"\nTop 10 most dangerous N-1 contingencies:")
    print(stress_df.head(10))

    n_lines = len(n.lines)
    lodf_line_line = lodf_full[:n_lines, :n_lines]
    flow_base = n.lines_t.p0.iloc[0].reindex(n.lines.index).fillna(0).values
    s_nom = n.lines['s_nom'].values

    # For the top contingency, show what overloads
    top_line = stress_df.index[0]
    top_idx = list(n.lines.index).index(top_line)
    _, overload_arr = _contingency_stress(top_idx, lodf_line_line, flow_base, s_nom)

    overload_series = pd.Series(overload_arr, index=n.lines.index)
    newly_overloaded = overload_series[overload_series > 0].sort_values(ascending=False)

    print(f"\nIf {top_line} trips "
          f"(base flow: {flow_base[top_idx]:.0f} MW, "
          f"s_nom: {s_nom[top_idx]:.0f} MW):")
    print(f"  {len(newly_overloaded)} lines become overloaded")
    print(f"  Top 5 newly-overloaded lines:")
    print(newly_overloaded.head(5))


    """
    0.01 -  0.1:  Trivial overland, no action
    0.1  -  1.5:  Mid overload, watch
    1.5  -  5.0:  Significant
    5.0  - 10.0:  Severe


    Top 10 most dangerous N-1 contingencies:
             stress
    line
    L2767  1.373614
    L3704  0.944403
    L2020  0.887711
    L2769  0.764663
    L3463  0.702501
    L2837  0.669233
    L3688  0.571059
    L2611  0.519040
    L2610  0.519040
    L3905  0.500465

    If L2767 trips (base flow: -164 MW, s_nom: 172 MW):
      12 lines become overloaded
      Top 5 newly-overloaded lines:
    name
    L2766    0.696648
    L3457    0.667709
    L3337    0.008618
    L2615    0.000270
    L2453    0.000231
    """
