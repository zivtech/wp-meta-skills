#!/usr/bin/env node
/* Browser smoke for a launch-ready WordPress Playground Blueprint.

Reads a launch-readiness preflight summary, opens the generated Playground
fragment URL, and verifies a visible assertion inside the Playground frames.
This is runtime evidence for one Blueprint artifact, not benchmark evidence.
*/

const fs = require("fs");
const os = require("os");
const path = require("path");
const { createRequire } = require("module");

const ROOT = path.resolve(__dirname, "../..");

function requireBundled(packageName) {
  const candidates = [
    process.env.CODEX_NODE_MODULES,
    ...(process.env.NODE_PATH ? process.env.NODE_PATH.split(path.delimiter) : []),
    path.join(ROOT, "node_modules"),
    path.join(os.homedir(), ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"),
  ].filter(Boolean);

  const errors = [];
  for (const modulesDir of candidates) {
    try {
      const requireFromDir = createRequire(path.join(modulesDir, ".codex-require.js"));
      return requireFromDir(packageName);
    } catch (error) {
      errors.push(`${modulesDir}: ${error.message}`);
    }
  }

  throw new Error(`Could not load ${packageName}. Tried:\n${errors.join("\n")}`);
}

async function launchChromium(chromium) {
  const executableCandidates = [
    process.env.WORDPRESS_BLUEPRINT_SMOKE_BROWSER,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    path.join(
      os.homedir(),
      ".cache/puppeteer/chrome-headless-shell/mac_arm-145.0.7632.77/chrome-headless-shell-mac-arm64/chrome-headless-shell",
    ),
  ].filter(Boolean);

  const attempts = [{ label: "playwright-default", options: {} }];
  for (const executablePath of executableCandidates) {
    if (fs.existsSync(executablePath)) {
      attempts.push({ label: executablePath, options: { executablePath } });
    }
  }

  const errors = [];
  for (const attempt of attempts) {
    try {
      return {
        browser: await chromium.launch({ headless: true, ...attempt.options }),
        label: attempt.label,
      };
    } catch (error) {
      errors.push(`${attempt.label}: ${error.message}`);
    }
  }

  throw new Error(`Could not launch Chromium. Tried:\n${errors.join("\n")}`);
}

function parseArgs(argv) {
  const args = {
    timeoutMs: 180000,
    viewportWidth: 1280,
    viewportHeight: 900,
  };
  for (let index = 2; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === "--preflight-summary") {
      args.preflightSummary = value;
      index += 1;
    } else if (key === "--fixture-id") {
      args.fixtureId = value;
      index += 1;
    } else if (key === "--expected-text") {
      args.expectedText = value;
      index += 1;
    } else if (key === "--expected-landing") {
      args.expectedLanding = value;
      index += 1;
    } else if (key === "--out-dir") {
      args.outDir = value;
      index += 1;
    } else if (key === "--timeout-ms") {
      args.timeoutMs = Number.parseInt(value, 10);
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${key}`);
    }
  }
  for (const required of ["preflightSummary", "fixtureId", "expectedText", "expectedLanding", "outDir"]) {
    if (!args[required]) {
      throw new Error(`--${required.replace(/[A-Z]/g, (char) => `-${char.toLowerCase()}`)} is required`);
    }
  }
  return args;
}

function truncate(value, limit = 1000) {
  if (!value) {
    return value;
  }
  return value.length > limit ? `${value.slice(0, limit)}...` : value;
}

function repoRelative(targetPath) {
  const absolute = path.resolve(targetPath);
  return path.relative(ROOT, absolute) || ".";
}

function loadAudit(preflightSummary, fixtureId) {
  const summary = JSON.parse(fs.readFileSync(preflightSummary, "utf8"));
  const audit = (summary.audits || []).find((row) => row.fixture_id === fixtureId);
  if (!audit) {
    throw new Error(`No audit found for fixture ${fixtureId}`);
  }
  if (!audit.launch_url) {
    throw new Error(`Audit for ${fixtureId} does not include a launch_url`);
  }
  if (audit.status !== "ready_for_manual_launch") {
    throw new Error(`Audit for ${fixtureId} is ${audit.status}, not ready_for_manual_launch`);
  }
  return { summary, audit };
}

async function frameSnapshots(page, expectedText, expectedLanding) {
  const snapshots = [];
  let visibleTextFound = false;
  let landingSeen = page.url().includes(expectedLanding);
  for (const frame of page.frames()) {
    const frameUrl = frame.url();
    landingSeen = landingSeen || frameUrl.includes(expectedLanding);
    try {
      const text = await frame.locator("body").innerText({ timeout: 1000 });
      visibleTextFound = visibleTextFound || text.includes(expectedText);
      snapshots.push({
        url: truncate(frameUrl, 200),
        text: truncate(text, 1200),
      });
    } catch (error) {
      snapshots.push({
        url: truncate(frameUrl, 200),
        error: truncate(error.message || String(error), 300),
      });
    }
  }
  return { snapshots, visibleTextFound, landingSeen };
}

function writeResults(outDir, result) {
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, "playground-smoke.json"), `${JSON.stringify(result, null, 2)}\n`);

  const lines = [
    "# WordPress Blueprint Playground Smoke",
    "",
    `- Run: \`${result.run_id}\``,
    `- Fixture: \`${result.fixture_id}\``,
    `- Status: \`${result.status}\``,
    `- Preflight summary: \`${result.preflight_summary}\``,
    `- Response status: \`${result.response_status}\``,
    `- Landing seen: \`${result.landing_seen}\``,
    `- Visible assertion found: \`${result.visible_text_found}\``,
    `- Browser: \`${result.browser_label}\``,
    "",
    "## Assertion",
    "",
    `- Expected landing: \`${result.expected_landing}\``,
    `- Expected visible text: \`${result.expected_text}\``,
    `- Observed landing URL: \`${result.observed_landing_url || "n/a"}\``,
    "",
    "## Console And Runtime Messages",
    "",
  ];
  if (result.console_messages.length) {
    for (const item of result.console_messages) {
      lines.push(`- \`${item.type}\`: ${item.text}`);
    }
  } else {
    lines.push("- No console or pageerror messages captured.");
  }
  lines.push(
    "",
    "## Boundary",
    "",
    "This smoke proves the named Blueprint artifact launched in the observed WordPress Playground session and rendered the expected visible assertion. It does not prove benchmark quality, long-run variance, production deployment, broad plugin behavior, or external-service behavior.",
    "",
  );
  fs.writeFileSync(path.join(outDir, "scorecard.md"), `${lines.join("\n")}`);
}

async function run() {
  const args = parseArgs(process.argv);
  const preflightSummary = path.resolve(args.preflightSummary);
  const outDir = path.resolve(args.outDir);
  const { audit } = loadAudit(preflightSummary, args.fixtureId);
  const { chromium } = requireBundled("playwright");
  const { browser, label } = await launchChromium(chromium);
  const page = await browser.newPage({
    viewport: { width: args.viewportWidth, height: args.viewportHeight },
  });
  const consoleMessages = [];
  page.on("console", (message) => {
    consoleMessages.push({ type: message.type(), text: truncate(message.text(), 400) });
  });
  page.on("pageerror", (error) => {
    consoleMessages.push({ type: "pageerror", text: truncate(error.message || String(error), 400) });
  });

  const response = await page.goto(audit.launch_url, { waitUntil: "domcontentloaded", timeout: 60000 });
  const started = Date.now();
  let lastSnapshots = [];
  let visibleTextFound = false;
  let landingSeen = false;
  while (Date.now() - started < args.timeoutMs) {
    const snapshotResult = await frameSnapshots(page, args.expectedText, args.expectedLanding);
    lastSnapshots = snapshotResult.snapshots;
    visibleTextFound = visibleTextFound || snapshotResult.visibleTextFound;
    landingSeen = landingSeen || snapshotResult.landingSeen;
    if (visibleTextFound) {
      break;
    }
    await page.waitForTimeout(3000);
  }

  const observedLanding = lastSnapshots.find((item) => item.url.includes(args.expectedLanding));
  const runtimeErrors = consoleMessages.filter((item) => item.type === "error" || item.type === "pageerror");
  const status = visibleTextFound && landingSeen && runtimeErrors.length === 0 ? "pass" : "fail";
  const result = {
    run_id: path.basename(outDir),
    created_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    status,
    fixture_id: args.fixtureId,
    preflight_summary: repoRelative(preflightSummary),
    static_blueprint_path: audit.blueprint_path,
    launch_url_source: "launch-preflight-summary.json#audits[].launch_url",
    expected_landing: args.expectedLanding,
    expected_text: args.expectedText,
    response_status: response ? response.status() : null,
    final_top_level_url: page.url(),
    observed_landing_url: observedLanding ? observedLanding.url : null,
    landing_seen: landingSeen,
    visible_text_found: visibleTextFound,
    browser_label: label,
    frame_count: page.frames().length,
    console_messages: consoleMessages,
    runtime_errors: runtimeErrors,
    frame_snapshots: lastSnapshots,
    negative_space: [
      "This proves one observed Playground launch for one generated Blueprint artifact.",
      "It does not prove benchmark quality, variance, production readiness, broad plugin behavior, or external-service behavior.",
    ],
  };

  writeResults(outDir, result);
  await browser.close();
  console.log(JSON.stringify(result, null, 2));
  process.exit(status === "pass" ? 0 : 1);
}

run().catch((error) => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
