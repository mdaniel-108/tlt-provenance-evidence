// Helpers to launch an isolated VS Code instance with the local extension build and drive it over CDP.
const { chromium } = require("D:/tlt/trace/tools/node_modules/playwright-core");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");

const CODE = "Code.exe";
const EXT = "D:/tlt/trace/src/llm-cp-experiment-main/extension";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function userSettings() {
  return {
    "llmCpTelemetry.backendUrl": "http://localhost:8000",
    // The extension records only while VS Code telemetry is on (extension README).
    "telemetry.telemetryLevel": "all",
    "update.mode": "none",
    "extensions.autoUpdate": false,
    "extensions.autoCheckUpdates": false,
    "workbench.startupEditor": "none",
    "workbench.tips.enabled": false,
    "workbench.enableExperiments": false,
    "security.workspace.trust.enabled": false,
    "git.enabled": false,
    "chat.disableAIFeatures": true,
    "github.copilot.enable": { "*": false },
    "editor.autoClosingBrackets": "never",
    "editor.autoClosingQuotes": "never",
    "editor.autoClosingOvertype": "never",
    "editor.autoSurround": "never",
    "editor.autoIndent": "none",
    "editor.formatOnType": false,
    "editor.formatOnPaste": false,
    "editor.quickSuggestions": { other: false, comments: false, strings: false },
    "editor.suggestOnTriggerCharacters": false,
    "editor.acceptSuggestionOnEnter": "off",
    "editor.parameterHints.enabled": false,
    "editor.inlineSuggest.enabled": false,
    "editor.insertSpaces": true,
    "editor.detectIndentation": false,
    "files.autoSave": "off",
    "files.eol": "\n",
    "window.restoreWindows": "none",
    "window.commandCenter": false,
    "python.languageServer": "None",
  };
}

function getJson(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => {
      let d = "";
      r.on("data", (c) => (d += c));
      r.on("end", () => {
        try { res(JSON.parse(d)); } catch (e) { rej(e); }
      });
    }).on("error", rej);
  });
}

async function launch(runDir, workspace, port) {
  const ud = path.join(runDir, "ud");
  const ex = path.join(runDir, "ext");
  fs.mkdirSync(path.join(ud, "User"), { recursive: true });
  fs.mkdirSync(ex, { recursive: true });
  fs.writeFileSync(path.join(ud, "User", "settings.json"), JSON.stringify(userSettings(), null, 1));
  const args = [
    "--user-data-dir", ud, "--extensions-dir", ex, `--extensionDevelopmentPath=${EXT}`,
    `--remote-debugging-port=${port}`, "--disable-workspace-trust", "--skip-welcome", "--skip-release-notes",
    "--disable-extension", "vscode.git", "--new-window", workspace,
  ];
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;
  const proc = spawn(CODE, args, { env, stdio: "ignore", detached: false });
  for (let i = 0; i < 120; i++) {
    try { await getJson(`http://127.0.0.1:${port}/json/version`); break; } catch { await sleep(500); }
  }
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  let page;
  for (let i = 0; i < 120 && !page; i++) {
    for (const c of browser.contexts()) for (const p of c.pages()) if (p.url().includes("workbench")) page = p;
    if (!page) await sleep(500);
  }
  await page.waitForSelector(".monaco-workbench", { timeout: 60000 });
  return { proc, browser, page };
}

module.exports = { launch, sleep, userSettings };
