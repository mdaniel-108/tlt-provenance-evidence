"""Reproduce the controlled trace validation from the scripted runs in data/traces/.

  python reproduce/traces.py

Runs code/analysis/tlt_trace_score.py on data/traces (keys and adjudication outputs of the 42 scripted runs and the
reduced packets) and compares the result with results/trace_validation.json.
"""
import json, sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / "code" / "analysis"))
import tlt_trace_score as ts  # noqa: E402

out = R / "reproduced"
out.mkdir(exist_ok=True)
ts.T = R / "data" / "traces"
ts.OUT = out / "trace_validation.json"
ts.main()
new = json.load(open(ts.OUT))
ref = json.load(open(R / "results" / "trace_validation.json"))
same = new == ref
print("\nMatches results/trace_validation.json." if same else "\nDiffers from results/trace_validation.json.")
