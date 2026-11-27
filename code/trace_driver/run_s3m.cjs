// S3M = S3 retyping at mid speed (typeHuman, 120 ms, no pauses), problems 1..3, ids M01..M03.
// Same driver, local stack (docker compose trace + ollama_shim.py) and retry rules as run_ext.cjs.
//   node run_s3h.cjs
const { spawnSync } = require("child_process");
const fs = require("fs");
const combos = [["S3M", 1], ["S3M", 2], ["S3M", 3]];
let seed = 6366;
const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
for (let i = combos.length - 1; i > 0; i--) { const j = Math.floor(rnd() * (i + 1)); [combos[i], combos[j]] = [combos[j], combos[i]]; }
const DEADLINE = Date.parse(process.env.TLT_DEADLINE || new Date(Date.now() + 2 * 3600e3).toISOString());
fs.writeFileSync("D:/tlt/trace/runs/plan_s3m.json", JSON.stringify(combos.map(([s, p], i) => ({ run: `M${String(i + 1).padStart(2, "0")}`, s, p })), null, 1));
for (const [i, [s, p]] of combos.entries()) {
  const base = `M${String(i + 1).padStart(2, "0")}`;
  if (Date.now() > DEADLINE) { console.log(new Date().toISOString(), "deadline reached, not starting", base); break; }
  for (const id of [base, base + "b", base + "c", base + "d"]) {
    if (fs.existsSync(`D:/tlt/trace/runs/${id}.json`)) {
      if (JSON.parse(fs.readFileSync(`D:/tlt/trace/runs/${id}.json`)).ok) break;
      continue;
    }
    console.log(new Date().toISOString(), "start", id, s, p);
    const r = spawnSync("node", ["D:/tlt/trace/scripts/run_scenario.cjs", id, s, String(p), String(9490 + i)],
      { cwd: "D:/tlt/trace/scripts", encoding: "utf8", timeout: 3600000 });
    fs.writeFileSync(`D:/tlt/trace/runs/${id}.log`, (r.stdout || "") + "\n--- stderr ---\n" + (r.stderr || ""));
    const ex = spawnSync("D:/tlt/trace/tools/venv/Scripts/python.exe", ["-I", "D:/tlt/trace/scripts/export_run.py", `trace_${id.toLowerCase()}`], { encoding: "utf8" });
    console.log(new Date().toISOString(), "end", id, "exit", r.status, "export", (ex.stdout || "").trim());
    if (r.status === 0) break;
    if (Date.now() > DEADLINE) break;
  }
}
