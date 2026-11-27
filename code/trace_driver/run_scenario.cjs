// Run one controlled-trace scenario in a fresh isolated VS Code profile against the LOCAL stack.
//   node run_scenario.cjs <run_id> <scenario S1..S12> <problem 1..3> <port>
// Writes D:/tlt/trace/runs/<run_id>.json (ground truth: actions with UTC times, final program).
const { launch, sleep } = require("./vsc.cjs");
const A = require("./actions.cjs");
const P = require("./problems.cjs");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const [runId, scen, probNo, portArg] = process.argv.slice(2);
const prob = P[probNo];
const port = Number(portArg || 9340);
const participant = `trace_${runId.toLowerCase()}`;
const WS = `D:/tlt/trace/ws/${runId}/solution`;
const FILE = path.join(WS, "main.py");
const actions = [];
const now = () => new Date().toISOString();
const act = (a, extra = {}) => { actions.push({ t: now(), action: a, ...extra }); console.log(now(), a, JSON.stringify(extra).slice(0, 200)); };
const read = () => fs.readFileSync(FILE, "utf8");

const RENAMES = ["left_val", "right_val", "items_list", "result_val", "word_count", "text_line", "idx", "acc"];

function assignedNames(code) {
  const names = [];
  const re = /^\s*(?:for\s+)?([A-Za-z_]\w*)(?:\s*,\s*([A-Za-z_]\w*))?\s*(?:=|in\b)/gm;
  let m;
  while ((m = re.exec(code))) for (const n of [m[1], m[2]]) if (n && !names.includes(n) && !["if", "while", "def", "return", "print", "import", "from"].includes(n)) names.push(n);
  return names;
}

async function askWithProposal(page, f, text) {
  // attached-file request; retry up to 2 times if no applicable proposal comes back
  for (let k = 0; k < 3; k++) {
    const before = (await A.proposalCards(f)).length;
    const q = k === 0 ? text : "Please propose the change to my attached file as an edit proposal.";
    const { sentAt } = await A.send(f, q, { attach: true });
    act("send_message_with_attached_file", { text: q, at: sentAt.toISOString() });
    await A.waitAnswer(f);
    const cards = await A.proposalCards(f);
    act("answer_received", { proposal_cards: cards.length - before, last_status: cards.length ? cards[cards.length - 1].status : null });
    if (cards.length > before && cards[cards.length - 1].actions.includes("apply")) return true;
  }
  return false;
}

async function askForCode(page, f, text) {
  for (let k = 0; k < 3; k++) {
    const nb = (await A.codeBlocks(f)).length;
    const q = k === 0 ? text : "Please show the complete Python program in one code block.";
    const { sentAt } = await A.send(f, q, { attach: false });
    act("send_message_no_attachment", { text: q, at: sentAt.toISOString() });
    await A.waitAnswer(f);
    const blocks = await A.codeBlocks(f);
    act("answer_received", { new_code_blocks: blocks.length - nb });
    if (blocks.length > nb) {
      // the program block: the longest new block that looks like Python (answers often add a shell usage block)
      let best = -1;
      for (let i = nb; i < blocks.length; i++) {
        const b = blocks[i];
        if (/\b(print|input|sys\.stdin)\b/.test(b) && !/^\s*(echo|python3?|\$)\s/m.test(b) && (best < 0 || b.length > blocks[best].length)) best = i;
      }
      if (best >= 0) return best;
    }
  }
  throw new Error("no code block in answers");
}

async function typeOwn(page, code, chunk = 8, pause = 120) {
  await A.focusEditor(page);
  act("type_by_hand_start", { chars: code.length });
  await A.typeChunks(page, code, chunk, pause);
  act("type_by_hand_end");
}

// after a paste + save: the file must hold exactly the copied block (otherwise the system clipboard held something else)
async function checkPasted(f, bi, prefix = "") {
  const want = prefix + (await A.codeBlocks(f))[bi];
  const norm = (x) => x.replace(/\r\n/g, "\n").replace(/\s+$/, "");
  if (norm(read()) !== norm(want)) throw new Error("pasted text differs from the copied code block");
  act("paste_verified", { chars: read().length });
}

async function saveFile(page, label = "save") {
  await A.focusEditor(page);
  await A.save(page);
  act(label, { sha256: crypto.createHash("sha256").update(read()).digest("hex").slice(0, 16) });
}

async function renameVars(page, n = 2) {
  const code = read();
  const names = assignedNames(code).filter((x) => x.length >= 1).slice(0, n);
  const used = [];
  for (const [i, name] of names.entries()) {
    let to = RENAMES.find((r) => !code.includes(r) && !used.includes(r));
    used.push(to);
    await A.focusEditor(page);
    await page.keyboard.press("Control+H");
    await sleep(500);
    await page.keyboard.press("Control+A");
    await page.keyboard.type(`\\b${name}\\b`);
    if (i === 0) await page.keyboard.press("Alt+R");   // regex mode (persists in the widget)
    await sleep(300);
    await page.keyboard.press("Tab");
    await sleep(200);
    await page.keyboard.press("Control+A");
    await page.keyboard.type(to);
    await sleep(300);
    await page.keyboard.press("Control+Alt+Enter");
    await sleep(500);
    await page.keyboard.press("Escape");
    act("rename_identifier_replace_all", { from: name, to });
  }
}

(async () => {
  fs.rmSync(WS, { recursive: true, force: true });
  fs.mkdirSync(WS, { recursive: true });
  fs.writeFileSync(FILE, "");
  const runDir = `D:/tlt/trace/vscode/${runId}`;
  fs.rmSync(runDir, { recursive: true, force: true });
  const { proc, browser, page } = await launch(runDir, WS, port);
  let ok = true, err = null;
  try {
    await sleep(4000);
    let f = await A.startSession(page, "dev-admission-code", participant);
    act("session_started", { participant });
    await A.selectThread(f, prob.thread);
    await A.openFile(page, "main.py");
    act("open_file", { file: "main.py" });
    const ask = `Problem: ${prob.statement} Write a Python solution.`;

    if (scen === "S1") {   // apply an AI-proposed edit
      await typeOwn(page, prob.buggy);
      await saveFile(page);
      if (!(await askWithProposal(page, f, `My solution is wrong. ${prob.bugHint} Please fix it.`))) throw new Error("no applicable proposal");
      await A.proposalAction(f, "apply");
      act("apply_proposal", { card: (await A.proposalCards(f)).slice(-1)[0] });
    } else if (scen === "S2") {   // copy from chat, paste into editor
      const bi = await askForCode(page, f, ask);
      const cp = await A.copyBlock(f, bi);
      act("copy_code_block_from_chat", { block_index: bi, copy_method: cp.method, copy_button_clicks: cp.clicks });
      await A.focusEditor(page);
      await A.paste(page);
      act("paste_into_editor");
      await saveFile(page);
      await checkPasted(f, bi);
    } else if (scen === "S3") {   // retype AI code by hand
      const bi = await askForCode(page, f, ask);
      const code = (await A.codeBlocks(f))[bi];
      act("read_code_block", { block_index: bi, chars: code.length });
      await sleep(3000);
      await typeOwn(page, code.replace(/\s+$/, "") + "\n", 6, 250);
      await saveFile(page);
    } else if (scen === "S3H") {  // 2026-11-22: retype AI code by hand at human speed (A.typeHuman)
      const bi = await askForCode(page, f, ask);
      const code = (await A.codeBlocks(f))[bi];
      act("read_code_block", { block_index: bi, chars: code.length });
      await sleep(3000);
      await A.focusEditor(page);
      act("type_by_hand_start", { chars: code.length, mode: "human" });
      const st = await A.typeHuman(page, code.replace(/\s+$/, "") + "\n", { seed: 6400 + Number(probNo) });
      act("type_by_hand_end", st);
      await saveFile(page);
      const norm = (x) => x.replace(/\r\n/g, "\n").replace(/\s+$/, "");
      act("typed_equals_block", { equal: norm(read()) === norm(code) });
    } else if (scen === "S3M") {  // retype AI code at mid speed (fluent copying, no long pauses)
      const bi = await askForCode(page, f, ask);
      const code = (await A.codeBlocks(f))[bi];
      act("read_code_block", { block_index: bi, chars: code.length });
      await sleep(3000);
      await A.focusEditor(page);
      act("type_by_hand_start", { chars: code.length, mode: "mid" });
      const st = await A.typeHuman(page, code.replace(/\s+$/, "") + "\n", { seed: 6500 + Number(probNo), msPerChar: 120, typoRate: 0.01, lookbacks: false });
      act("type_by_hand_end", st);
      await saveFile(page);
      const norm = (x) => x.replace(/\r\n/g, "\n").replace(/\s+$/, "");
      act("typed_equals_block", { equal: norm(read()) === norm(code) });
    } else if (scen === "S4") {   // rename identifiers after an AI insertion
      await typeOwn(page, prob.buggy);
      await saveFile(page);
      if (!(await askWithProposal(page, f, `My solution is wrong. ${prob.bugHint} Please rewrite my whole program in the attached file so that it is correct.`))) throw new Error("no applicable proposal");
      await A.proposalAction(f, "apply");
      act("apply_proposal", { card: (await A.proposalCards(f)).slice(-1)[0] });
      await sleep(5000);
      await renameVars(page, 2);
      await saveFile(page);
    } else if (scen === "S5") {   // apply, undo, then rewrite independently
      await typeOwn(page, prob.buggy);
      await saveFile(page);
      if (!(await askWithProposal(page, f, `My solution is wrong. ${prob.bugHint} Please rewrite my whole program in the attached file so that it is correct.`))) throw new Error("no applicable proposal");
      await A.proposalAction(f, "apply");
      act("apply_proposal");
      await sleep(4000);
      await A.proposalAction(f, "undo");
      act("undo_proposal", { card: (await A.proposalCards(f)).slice(-1)[0] });
      await sleep(3000);
      await A.focusEditor(page);
      await A.selectAllDelete(page);
      act("delete_all_text");
      await typeOwn(page, prob.own2, 6, 200);
      await saveFile(page);
    } else if (scen === "S6") {   // change after the last AI interaction, then submit
      const bi = await askForCode(page, f, ask);
      const cp = await A.copyBlock(f, bi);
      act("copy_code_block_from_chat", { block_index: bi, copy_method: cp.method, copy_button_clicks: cp.clicks });
      await A.focusEditor(page);
      await A.paste(page);
      act("paste_into_editor");
      await saveFile(page);
      await checkPasted(f, bi);
      act("last_ai_interaction_before_this_point");
      await sleep(20000);
      await A.focusEditor(page);
      await page.keyboard.press("Control+Home");
      await A.typeChunks(page, "# solution for the practice problem\n", 6, 150);
      act("manual_edit", { what: "insert header comment line" });
      await saveFile(page, "intermediate_save");
      await sleep(15000);
      await A.focusEditor(page);
      await page.keyboard.press("Control+End");
      await A.typeChunks(page, "\n" + prob.tweak.append, 6, 150);
      act("manual_edit", { what: "append trailing comment line" });
      await saveFile(page);
    } else if (scen === "S7") {   // reuse code from an earlier response
      const bi = await askForCode(page, f, ask);
      act("earlier_response_with_code", { block_index: bi });
      await sleep(10000);
      await askForCode(page, f, "Separately: how do I read a large amount of input quickly in Python? Show a short example.");
      act("later_unrelated_response");
      await sleep(20000);
      const cp = await A.copyBlock(f, bi);
      act("copy_code_block_from_EARLIER_response", { block_index: bi, copy_method: cp.method, copy_button_clicks: cp.clicks });
      await A.focusEditor(page);
      await A.paste(page);
      act("paste_into_editor");
      await saveFile(page);
      await checkPasted(f, bi);
    } else if (scen === "S8") {   // send own code, accept an echoing answer
      await typeOwn(page, prob.own);
      await saveFile(page);
      const msg = `Problem: ${prob.statement}\nHere is my solution. Is it correct? Please reply with the final program in a code block.\n\n\`\`\`python\n${prob.own}\`\`\``;
      const bi = await askForCode(page, f, msg);
      const echoed = (await A.codeBlocks(f))[bi];
      act("echo_answer_received", { block_index: bi, chars: echoed.length });
      const cp = await A.copyBlock(f, bi);
      act("copy_code_block_from_chat", { block_index: bi, copy_method: cp.method, copy_button_clicks: cp.clicks });
      await A.focusEditor(page);
      await A.selectAllDelete(page);
      await A.paste(page);
      act("replace_file_with_pasted_answer");
      await saveFile(page);
      await checkPasted(f, bi);
    } else if (scen === "S9") {   // no AI use
      await sleep(5000);
      await typeOwn(page, prob.own, 6, 200);
      await saveFile(page);
    } else if (scen === "S10") {   // AI answer received but not used; own short solution typed
      const bi = await askForCode(page, f, ask);
      act("answer_received_not_used", { block_index: bi });
      await sleep(10000);
      await typeOwn(page, prob.own2, 6, 200);
      await saveFile(page);
    } else if (scen === "S11") {   // own code written first, then the assistant explains it; code kept
      await typeOwn(page, prob.own, 6, 200);
      await saveFile(page);
      const q = "Can you explain what my program in the attached file does? Please do not change it.";
      const { sentAt } = await A.send(f, q, { attach: true });
      act("send_message_with_attached_file", { text: q, at: sentAt.toISOString() });
      await A.waitAnswer(f);
      act("answer_received_not_used");
      await sleep(5000);
      await saveFile(page);
    } else if (scen === "S12") {   // AI answer received but not used; own longer solution typed
      const bi = await askForCode(page, f, ask);
      act("answer_received_not_used", { block_index: bi });
      await sleep(10000);
      await typeOwn(page, prob.own, 6, 200);
      await saveFile(page);
    } else throw new Error("unknown scenario " + scen);

    await sleep(3000);
    await A.markSubmission(page, prob.thread);
    act("submission_marker", { problem: prob.thread });
    // let the uploader flush telemetry and source (idle polling is 10 s)
    await sleep(40000);
  } catch (e) {
    ok = false; err = String(e && e.stack || e);
    console.error(e);
    await page.screenshot({ path: `D:/tlt/trace/runs/${runId}_error.png` }).catch(() => {});
  }
  const finalCode = fs.existsSync(FILE) ? read() : null;
  const sub = actions.find((a) => a.action === "submission_marker");
  fs.mkdirSync("D:/tlt/trace/runs", { recursive: true });
  fs.writeFileSync(`D:/tlt/trace/runs/${runId}.json`, JSON.stringify({
    run_id: runId, scenario: scen, problem: Number(probNo), participant, ok, error: err,
    submission_time: sub ? sub.t : null, final_code: finalCode, actions,
  }, null, 1));
  await browser.close().catch(() => {});
  proc.kill();
  await sleep(3000);
  process.exit(ok ? 0 : 2);
})();
