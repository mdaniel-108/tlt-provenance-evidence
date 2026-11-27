"""Reproduce Table X (one learning-analytics question answered with record labels and with detector labels) and the
learner profiles from data/, and compare them with results/la_demo.json.

  python reproduce/learning_analytics.py
"""
import json, os, runpy
from pathlib import Path

R = Path(__file__).resolve().parents[1]
out = R / "reproduced" / "la_demo.json"
out.parent.mkdir(exist_ok=True)
os.environ["LA_OUT"] = str(out)
runpy.run_path(str(R / "code" / "analysis" / "tlt_la_demo.py"), run_name="__main__")
new, ref = json.loads(out.read_text()), json.loads((R / "results" / "la_demo.json").read_text())
same = new == ref
print("\nAll values match results/la_demo.json." if same else "\nSome values differ from results/la_demo.json.")
