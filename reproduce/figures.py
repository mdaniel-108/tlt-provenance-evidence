"""Redraw the manuscript figures from the aggregate results in results/.

  python reproduce/figures.py

Writes PDF figures to reproduced/figures (the copies in figures/ were made the same way).
"""
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / "code" / "analysis"))
import tlt_figures as f  # noqa: E402

f.OUT = R / "results"
f.FIG = R / "reproduced" / "figures"
f.FIG.mkdir(parents=True, exist_ok=True)
for fn in (f.fig_transfer, f.fig_configs, f.fig_funnel, f.fig_operating, f.fig_shift, f.fig_trace, f.fig_reduced, f.fig_echo):
    fn()
print("figures written to", f.FIG)
