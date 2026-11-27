// UI-level actions on the isolated VS Code window (workbench page + LLM-CP chat webview).
const { sleep } = require("./vsc.cjs");

const MOD = "Control";

async function chatFrame(page, timeout = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    for (const f of page.frames()) {
      if (!f.url().startsWith("vscode-webview://")) continue;
      try {
        if (await f.$("#root, .admission, .message-input-frame__textarea")) {
          if (await f.$(".admission, .message-input-frame__textarea, .thread-switcher")) return f;
        }
      } catch { /* detached */ }
    }
    await sleep(500);
  }
  throw new Error("chat webview frame not found");
}

async function command(page, title) {
  await page.keyboard.press("Escape");
  await page.keyboard.press(`${MOD}+Shift+P`);
  await page.waitForSelector(".quick-input-widget:not([style*='display: none']) input", { timeout: 10000 });
  await page.keyboard.type(title, { delay: 10 });
  await sleep(700);
  await page.keyboard.press("Enter");
  await sleep(700);
}

async function startSession(page, code, participant, log) {
  await command(page, "LLM-CP: Open Chat");
  let f = await chatFrame(page);
  const startBtn = await f.$(".admission__actions button");
  if (startBtn) await startBtn.click();
  // code step
  await f.waitForSelector(".admission__input", { timeout: 30000 });
  await f.fill(".admission__input", code);
  await f.click(".admission__form button[type=submit]");
  // participant step: wait for the input to be emptied/re-rendered for the second step
  let ok = false;
  for (let i = 0; i < 120 && !ok; i++) {
    await sleep(500);
    ok = (await f.$eval(".admission__label", (e) => e.textContent).catch(() => "")) === "Participant ID";
  }
  if (!ok) throw new Error("participant step not reached");
  await f.fill(".admission__input", participant);
  await f.click(".admission__form button[type=submit]");
  // chat ready: textarea present
  f = await chatFrame(page);
  await f.waitForSelector(".message-input-frame__textarea", { timeout: 90000 });
  log && log("session ready");
  return f;
}

async function selectThread(f, title) {
  for (let i = 0; i < 60; i++) {
    const ok = await f.$$eval(".thread-switcher select option", (os, t) => os.some((o) => o.textContent === t && !o.disabled), title);
    if (ok) break;
    await sleep(500);
  }
  const value = await f.$$eval(".thread-switcher select option", (os, t) => os.find((o) => o.textContent === t).value, title);
  await f.selectOption(".thread-switcher select", value);
  await sleep(1500);
}

async function attachmentChips(f) {
  return f.$$eval(".file-attachments button[aria-label^='Remove attachment']", (bs) => bs.map((b) => b.getAttribute("aria-label")));
}

/** Send a chat message; attach=false removes the auto-attached current file first. */
async function send(f, text, { attach }) {
  await sleep(800);
  const chips = await attachmentChips(f);
  if (!attach && chips.length) {
    await f.click(".file-attachments button[aria-label^='Remove attachment']");
    await sleep(300);
  }
  if (attach && !chips.length) throw new Error("expected the current file to be auto-attached");
  const nBefore = await f.$$eval(".message-list .copy-button, .message-list [class*=assistant]", (x) => x.length).catch(() => 0);
  await f.fill(".message-input-frame__textarea", text);
  // wait for the send button to be enabled (the ledger may still hold the previous call)
  for (let i = 0; i < 600; i++) {
    const en = await f.$$eval(".message-input-frame__controls button", (bs) => {
      const b = bs[bs.length - 1];
      return b && !b.disabled && /Send/.test(b.textContent);
    });
    if (en) break;
    await sleep(500);
  }
  const sentAt = new Date();
  await f.click(".message-input-frame__controls button:last-child");
  return { sentAt, nBefore };
}

/** Wait until the answer is finished (Stop button gone and Send back). */
async function waitAnswer(f, timeout = 1500000) {
  const t0 = Date.now();
  await sleep(1500);
  while (Date.now() - t0 < timeout) {
    const st = await f.$$eval(".message-input-frame__controls button", (bs) => bs.map((b) => b.textContent));
    if (!st.some((s) => /Stop/.test(s))) {
      await sleep(1500);
      const st2 = await f.$$eval(".message-input-frame__controls button", (bs) => bs.map((b) => b.textContent));
      if (!st2.some((s) => /Stop/.test(s))) return new Date();
    }
    await sleep(1000);
  }
  throw new Error("answer timeout");
}

async function proposalCards(f) {
  return f.$$eval(".proposal-card", (cs) => cs.map((c) => ({
    cls: c.className,
    path: c.querySelector(".proposal-card__path")?.textContent,
    actions: [...c.querySelectorAll(".proposal-card__actions button")].map((b) => b.className.replace(/.*--/, "")),
    status: c.querySelector(".proposal-card__status")?.textContent,
  })));
}

async function proposalAction(f, action, idx = -1) {
  const cards = await f.$$(".proposal-card");
  const card = cards[idx < 0 ? cards.length + idx : idx];
  const b = await card.$(`.proposal-card__button--${action}`);
  if (!b) throw new Error(`no ${action} button on proposal card`);
  await b.click();
  await sleep(2500);
}

/** Last assistant code block text (as rendered). */
async function codeBlocks(f) {
  return f.$$eval(".message-list pre code", (cs) => cs.map((c) => c.textContent));
}

/** Click the copy button of the n-th code block (negative from the end). */
async function copyBlock(f, idx = -1) {
  const pres = await f.$$(".message-list pre");
  const pre = pres[idx < 0 ? pres.length + idx : idx];
  await pre.evaluate((e) => e.scrollIntoView({ block: "center" }));
  await sleep(400);
  await pre.hover({ force: true });
  await sleep(300);
  const h = await f.evaluateHandle((p) => {
    let n = p;
    for (let i = 0; i < 5 && n; i++, n = n.parentElement) {
      const c = n.querySelector(".copy-button");
      if (c) return c;
    }
    return null;
  }, pre);
  const b = h.asElement();
  if (!b) throw new Error("copy button not found");
  // the button shows "Copied" (for 1.5 s) only after navigator.clipboard.writeText resolved; poll for it
  const page = f.page();
  const msgs = [];
  const onMsg = (m) => { if (/copy|clipboard|focus/i.test(m.text())) msgs.push(m.type() + ": " + m.text().slice(0, 200)); };
  page.on("console", onMsg);
  let label = null, focus = null, clicks = 0;
  // a point inside the button that is not covered by the code text (long first lines overlap the button)
  const pos = await b.evaluate((el) => {
    const r = el.getBoundingClientRect();
    for (let y = 1; y < r.height; y += 2) for (let x = 1; x < r.width; x += 2) {
      const h = document.elementFromPoint(r.x + x, r.y + y);
      if (h && el.contains(h)) return { x, y };
    }
    return null;
  });
  if (!pos) {
    // the button cannot be hit: select the block's text and press Ctrl+C (the extension copies the selection)
    page.off("console", onMsg);
    await emulateFocus(page);
    await pre.evaluate((p) => {
      const c = p.querySelector("code") || p;
      const r = document.createRange();
      r.selectNodeContents(c);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(r);
    });
    await sleep(300);
    await page.keyboard.press(`${MOD}+C`);
    await sleep(800);
    await pre.evaluate(() => window.getSelection().removeAllRanges());
    return { method: "select_text_ctrl_c", clicks: 0 };
  }
  try {
    for (let k = 0; k < 3 && label !== "Copied"; k++) {
      await emulateFocus(page);
      await pre.hover({ force: true }).catch(() => {});
      await b.click({ force: true, position: pos });
      clicks++;
      for (let i = 0; i < 14 && label !== "Copied"; i++) {
        await sleep(100);
        label = await b.getAttribute("aria-label").catch(() => null);
      }
      if (label !== "Copied") {
        focus = await f.evaluate(() => document.hasFocus()).catch(() => "n/a");
        await sleep(2000);
      }
    }
  } finally { page.off("console", onMsg); }
  if (label !== "Copied") throw new Error(`copy did not reach the clipboard after ${clicks} clicks (label: ${label}; hasFocus: ${focus}; console: ${msgs.join(" | ") || "none"})`);
  return { method: "copy_button", clicks };
}

/** Make the window count as focused even when another desktop window is in front (CDP focus emulation,
 *  applied to the workbench page and to any out-of-process webview frame). The copy button itself is unchanged. */
async function emulateFocus(page) {
  for (const t of [page, ...page.frames()]) {
    try {
      const s = await page.context().newCDPSession(t);
      await s.send("Emulation.setFocusEmulationEnabled", { enabled: true });
    } catch { /* same-process frame: covered by the page session */ }
  }
}

async function focusEditor(page) {
  await page.keyboard.press("Escape");
  await command(page, "View: Focus Active Editor Group");
  await sleep(300);
}

async function openFile(page, name) {
  await page.keyboard.press(`${MOD}+P`);
  await sleep(400);
  await page.keyboard.type(name, { delay: 10 });
  await sleep(800);
  await page.keyboard.press("Enter");
  await sleep(1200);
}

async function selectAllDelete(page) {
  await page.keyboard.press(`${MOD}+A`);
  await page.keyboard.press("Delete");
  await sleep(200);
}

async function save(page) {
  await page.keyboard.press(`${MOD}+S`);
  await sleep(800);
}

async function gotoLine(page, line) {
  await page.keyboard.press(`${MOD}+G`);
  await sleep(300);
  await page.keyboard.type(String(line));
  await page.keyboard.press("Enter");
  await sleep(300);
}

/**
 * 2026-11-22 (S3H): type like a person copying code from the chat by hand.
 * Seeded and reproducible. Per keystroke a log-normal gap around `msPerChar` (median ~4.5 chars/s at 220 ms),
 * a longer gap after each newline, and a "look back at the chat" pause every 25-60 characters (2-6 s, longer than
 * the extension's 1.5 s edit debounce). With probability `typoRate` a wrong neighbouring letter is typed and
 * removed with Backspace, so the final text equals `text`. Returns timing stats for the ground-truth log.
 */
async function typeHuman(page, text, { seed = 1, msPerChar = 220, typoRate = 0.02, lookbacks: doLook = true } = {}) {
  let s = seed >>> 0;
  const rnd = () => ((s = (Math.imul(s, 1103515245) + 12345) >>> 0) / 4294967296);
  const gauss = () => Math.sqrt(-2 * Math.log(rnd() + 1e-12)) * Math.cos(2 * Math.PI * rnd());
  const gap = (m) => Math.max(40, m * Math.exp(0.35 * gauss()));
  const t0 = Date.now();
  let typos = 0, lookbacks = 0, nextLook = 25 + Math.floor(rnd() * 36);
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch !== "\n" && /[a-z]/.test(ch) && rnd() < typoRate) {
      const wrong = String.fromCharCode(97 + ((ch.charCodeAt(0) - 97 + 1 + Math.floor(rnd() * 3)) % 26));
      await page.keyboard.type(wrong);
      await sleep(gap(msPerChar * 1.5));
      await page.keyboard.press("Backspace");
      await sleep(gap(msPerChar));
      typos++;
    }
    if (ch === "\n") await page.keyboard.press("Enter");
    else await page.keyboard.type(ch);
    await sleep(gap(ch === "\n" ? msPerChar * 3 : msPerChar));
    if (doLook && --nextLook <= 0) {
      await sleep(2000 + rnd() * 4000);
      lookbacks++;
      nextLook = 25 + Math.floor(rnd() * 36);
    }
  }
  const sec = (Date.now() - t0) / 1000;
  return { chars: text.length, seconds: Math.round(sec * 10) / 10, chars_per_s: Math.round((text.length / sec) * 100) / 100, typos, lookbacks };
}

/** Type text in small chunks with pauses (a person retyping). */
async function typeChunks(page, text, chunk = 6, pause = 250) {
  for (let i = 0; i < text.length; i += chunk) {
    const piece = text.slice(i, i + chunk);
    for (const ch of piece) {
      if (ch === "\n") await page.keyboard.press("Enter");
      else await page.keyboard.type(ch, { delay: 15 });
    }
    await sleep(pause);
  }
}

async function paste(page) {
  await page.keyboard.press(`${MOD}+V`);
  await sleep(500);
}

async function undo(page) {
  await page.keyboard.press(`${MOD}+Z`);
  await sleep(300);
}

/** Replace all occurrences via the editor's Replace widget. */
async function replaceAll(page, from, to) {
  await page.keyboard.press(`${MOD}+H`);
  await sleep(500);
  await page.keyboard.press(`${MOD}+A`);
  await page.keyboard.type(from);
  await sleep(200);
  await page.keyboard.press("Tab");
  await page.keyboard.press(`${MOD}+A`);
  await page.keyboard.type(to);
  await sleep(200);
  await page.keyboard.press(`${MOD}+Alt+Enter`);
  await sleep(400);
  await page.keyboard.press("Escape");
  await sleep(300);
}

async function markSubmission(page, problemTitle) {
  await command(page, "LLM-CP: Record Submission/Give Up");
  await sleep(800);
  // problem pick
  await page.keyboard.type(problemTitle, { delay: 10 });
  await sleep(500);
  await page.keyboard.press("Enter");
  await sleep(800);
  // kind pick (first item: submission)
  await page.keyboard.press("Enter");
  await sleep(800);
  // optional note
  await page.keyboard.press("Enter");
  await sleep(800);
}

module.exports = {
  chatFrame, command, startSession, selectThread, send, waitAnswer, proposalCards, proposalAction, codeBlocks,
  copyBlock, focusEditor, openFile, selectAllDelete, save, gotoLine, typeChunks, typeHuman, paste, undo, replaceAll, markSubmission,
  attachmentChips, emulateFocus,
};
