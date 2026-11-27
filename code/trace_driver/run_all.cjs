// Run all 27 controlled-trace runs (S1..S9 x problems 1..3) in a shuffled order, one at a time.
// A failed run is retried once under a new run id (suffix "b"); both are kept in runs/.
const { spawnSync } = require("child_process");
const fs = require("fs");

const combos = [];
for (let s = 1; s <= 9; s++) for (let p = 1; p <= 3; p++) combos.push([`S${s}`, p]);
// deterministic shuffle (seed 6363) so run order does not follow scenario order
let seed = 6363;
const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
for (let i = combos.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [combos[i], combos[j]] = [combos[j], combos[i]]; }
const DEADLINE = Date.parse(process.env.TLT_DEADLINE || "2026-11-21T07:10:00Z");   // no new run after this (3-hour limit)
const lost = new Set();
const only = process.argv[2] ? process.argv[2].split(",") : null;
fs.writeFileSync("D:/tlt/trace/runs/plan.json", JSON.stringify(combos.map(([s, p], i) => ({ run: `R${String(i + 1).padStart(2, "0")}`, s, p })), null, 1));

for (const [i, [s, p]] of combos.entries()) {
  const base = `R${String(i + 1).padStart(2, "0")}`;
  if (only && !only.includes(base)) continue;
  // 2026-11-21: clipboard scenarios re-enabled (CDP focus emulation + copy/paste verification in the driver)
  if (Date.now() > DEADLINE) { console.log(new Date().toISOString(), "deadline reached, not starting", base); break; }
  if (lost.size > 27 - 14) { console.log(new Date().toISOString(), "stop: fewer than half of the 27 runs can still be produced"); break; }
  let done = false;
  for (const id of [base, base + "b", base + "c", base + "d", base + "e", base + "f", base + "g"]) {
    if (fs.existsSync(`D:/tlt/trace/runs/${id}.json`)) {
      if (JSON.parse(fs.readFileSync(`D:/tlt/trace/runs/${id}.json`)).ok) { done = true; break; }
      continue;   // a failed id is never rerun under the same participant
    }
    console.log(new Date().toISOString(), "start", id, s, p);
    const r = spawnSync("node", ["D:/tlt/trace/scripts/run_scenario.cjs", id, s, String(p), String(9350 + i)],
      { cwd: "D:/tlt/trace/scripts", encoding: "utf8", timeout: 3600000 });
    fs.writeFileSync(`D:/tlt/trace/runs/${id}.log`, (r.stdout || "") + "\n--- stderr ---\n" + (r.stderr || ""));
    const ex = spawnSync("D:/tlt/trace/tools/venv/Scripts/python.exe", ["-I", "D:/tlt/trace/scripts/export_run.py", `trace_${id.toLowerCase()}`], { encoding: "utf8" });
    console.log(new Date().toISOString(), "end", id, "exit", r.status, "export", (ex.stdout || "").trim());
    if (r.status === 0) { done = true; break; }
    if (Date.now() > DEADLINE) break;
  }
  if (!done && !(Date.now() > DEADLINE)) lost.add(base);
}
