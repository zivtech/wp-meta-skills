#!/usr/bin/env node
/* Narrow WordPress editor smoke for a registered block.

This script assumes wp-env is already running. It logs into wp-admin, opens the
post editor, and verifies that the requested block is visible to the editor-side
block registry. When --insert-render-smoke is set, it also inserts the block,
publishes the post, and verifies the server-rendered block text on the frontend.
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
    process.env.WORDPRESS_EDITOR_SMOKE_BROWSER,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    path.join(os.homedir(), ".cache/puppeteer/chrome-headless-shell/mac_arm-145.0.7632.77/chrome-headless-shell-mac-arm64/chrome-headless-shell"),
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
    username: "admin",
    password: "password",
    timeoutMs: 60000,
    insertRenderSmoke: false,
    interactivitySmoke: false,
    deprecationSmoke: false,
    expectedMigratedText: "Runtime block smoke: Legacy runtime smoke",
    expectedMigratedAttributeName: "content",
    expectedMigratedAttribute: "Legacy runtime smoke",
    expectedSerializedMarker: "<strong>Runtime block smoke:</strong>",
  };
  for (let index = 2; index < argv.length; index += 1) {
    const key = argv[index];
    const value = argv[index + 1];
    if (key === "--url") {
      args.url = value;
      index += 1;
    } else if (key === "--block-name") {
      args.blockName = value;
      index += 1;
    } else if (key === "--username") {
      args.username = value;
      index += 1;
    } else if (key === "--password") {
      args.password = value;
      index += 1;
    } else if (key === "--timeout-ms") {
      args.timeoutMs = Number.parseInt(value, 10);
      index += 1;
    } else if (key === "--insert-render-smoke") {
      args.insertRenderSmoke = true;
    } else if (key === "--expected-frontend-selector") {
      args.expectedFrontendSelector = value;
      index += 1;
    } else if (key === "--expected-frontend-text") {
      args.expectedFrontendText = value;
      index += 1;
    } else if (key === "--interactivity-smoke") {
      args.interactivitySmoke = true;
    } else if (key === "--deprecation-smoke") {
      args.deprecationSmoke = true;
    } else if (key === "--post-id") {
      args.postId = Number.parseInt(value, 10);
      index += 1;
    } else if (key === "--expected-migrated-text") {
      args.expectedMigratedText = value;
      index += 1;
    } else if (key === "--expected-migrated-attribute-name") {
      args.expectedMigratedAttributeName = value;
      index += 1;
    } else if (key === "--expected-migrated-attribute") {
      args.expectedMigratedAttribute = value;
      index += 1;
    } else if (key === "--expected-serialized-marker") {
      args.expectedSerializedMarker = value;
      index += 1;
    } else {
      throw new Error(`Unknown argument: ${key}`);
    }
  }
  if (!args.url) {
    throw new Error("--url is required");
  }
  if (!args.blockName) {
    throw new Error("--block-name is required");
  }
  if (args.interactivitySmoke && !args.insertRenderSmoke) {
    throw new Error("--interactivity-smoke requires --insert-render-smoke");
  }
  if (args.insertRenderSmoke && (!args.expectedFrontendSelector || !args.expectedFrontendText)) {
    throw new Error("--insert-render-smoke requires exact frontend selector and text");
  }
  if (args.deprecationSmoke && !args.postId) {
    throw new Error("--deprecation-smoke requires --post-id");
  }
  return args;
}

function joinUrl(base, pathname) {
  return new URL(pathname, base.endsWith("/") ? base : `${base}/`).toString();
}

function truncate(value, limit = 1000) {
  if (!value) {
    return value;
  }
  return value.length > limit ? `${value.slice(0, limit)}...` : value;
}

function errorMessage(error) {
  return error && (error.stack || error.message) ? error.stack || error.message : String(error);
}

function postUrl(base, postId) {
  const url = new URL(base.endsWith("/") ? base : `${base}/`);
  url.searchParams.set("p", String(postId));
  return url.toString();
}

function defaultBlockClassName(blockName) {
  const normalized = blockName.startsWith("core/") ? blockName.slice("core/".length) : blockName;
  return `wp-block-${normalized.replace(/\//g, "-").replace(/[^a-z0-9_-]/gi, "-").toLowerCase()}`;
}

function verifyFrontendRender(wrapperText, wrapperSelector, expectedText) {
  if (!expectedText || !wrapperSelector) {
    throw new Error("frontend render assertion must be explicit");
  }
  const frontendTextFound = wrapperText.includes(expectedText);
  if (!frontendTextFound) {
    throw new Error(`frontend render text not found in ${wrapperSelector}`);
  }
  return {
    frontendTextFound,
    wrapperSelector,
    wrapperText: truncate(wrapperText),
  };
}

function verifyInteractivityResult(beforeText, afterText, expectedBeforeText = "0", expectedAfterText = "1") {
  if (beforeText !== expectedBeforeText) {
    throw new Error(`interactivity initial text mismatch: expected ${expectedBeforeText}, got ${beforeText}`);
  }
  if (afterText !== expectedAfterText) {
    throw new Error(`interactivity updated text mismatch: expected ${expectedAfterText}, got ${afterText}`);
  }
  if (beforeText === afterText) {
    throw new Error("interactivity click did not change frontend text");
  }
  return {
    beforeText,
    afterText,
    clickChangedText: true,
  };
}

function verifyDeprecationResult(result) {
  if (!result.targetBlockFound) {
    throw new Error("deprecated block was not parsed as the current block");
  }
  if (!result.migratedAttributeFound) {
    throw new Error(
      `migrated attribute not found: ${result.expectedMigratedAttributeName}=${result.expectedMigratedAttribute}; attributes=${JSON.stringify(
        result.targetAttributes || {},
      )}`,
    );
  }
  if (!result.serializedMarkerFound) {
    throw new Error(
      `current serialized block marker not found: ${result.expectedSerializedMarker}; before=${truncate(
        result.serializedBeforeSave || "",
      )}; migrated=${truncate(result.serializedMigratedBlocks || "")}; after=${truncate(result.serializedAfterSave || "")}`,
    );
  }
  if (result.invalidBlockUIFound) {
    throw new Error("editor reported invalid deprecated block content");
  }
  if (result.didSaveFail) {
    throw new Error("editor save request failed for deprecated block migration");
  }
  return {
    targetBlockFound: true,
    migratedAttributeFound: true,
    serializedMarkerFound: true,
    invalidBlockUIFound: false,
    didSaveFail: false,
  };
}

async function verifyFrontendInteractivity(page, wrapperClass, timeout) {
  const interactionTimeout = Math.min(timeout, 5000);
  const wrapper = page.locator(`.${wrapperClass}`).first();
  const interactiveRootFound = (await wrapper.getAttribute("data-wp-interactive", { timeout: interactionTimeout })) !== null;
  if (!interactiveRootFound) {
    throw new Error(`data-wp-interactive not found on .${wrapperClass}`);
  }

  const output = wrapper.locator("[data-wp-text]").first();
  const button = wrapper.locator("button[data-wp-on--click]").first();
  const beforeText = (await output.innerText({ timeout: interactionTimeout })).trim();
  await button.click({ timeout: interactionTimeout });
  await page.waitForFunction(
    ({ selector, before }) => {
      const element = document.querySelector(selector);
      return element && element.textContent.trim() !== before;
    },
    { selector: `.${wrapperClass} [data-wp-text]`, before: beforeText },
    { timeout: interactionTimeout },
  );
  const afterText = (await output.innerText({ timeout: interactionTimeout })).trim();
  return {
    interactiveRootFound,
    ...verifyInteractivityResult(beforeText, afterText),
  };
}

async function main() {
  const args = parseArgs(process.argv);
  const { chromium } = requireBundled("playwright");
  const deadline = Date.now() + args.timeoutMs;
  const stages = [];
  const pageErrors = [];
  const consoleErrors = [];
  let launched = { label: null };
  let browser = null;
  let page = null;

  async function runStage(name, fn, capMs = 30000) {
    const started = Date.now();
    const remaining = deadline - started - 1000;
    const timeoutMs = Math.max(1000, Math.min(capMs, remaining));
    let timer = null;
    if (remaining <= 0) {
      const message = `total timeout exhausted before ${name}`;
      stages.push({ name, status: "fail", durationMs: 0, error: message });
      throw new Error(message);
    }

    try {
      const result = await Promise.race([
        fn(timeoutMs),
        new Promise((_, reject) => {
          timer = setTimeout(() => reject(new Error(`${name} timed out after ${timeoutMs}ms`)), timeoutMs);
        }),
      ]);
      stages.push({ name, status: "pass", durationMs: Date.now() - started });
      return result;
    } catch (error) {
      stages.push({ name, status: "fail", durationMs: Date.now() - started, error: truncate(errorMessage(error)) });
      throw new Error(`${name} failed: ${errorMessage(error)}`);
    } finally {
      if (timer) {
        clearTimeout(timer);
      }
    }
  }

  async function pageSnapshot() {
    if (!page) {
      return null;
    }
    return {
      url: page.url(),
      title: await page.title().catch(() => ""),
      bodySnippet: truncate(
        await page
          .locator("body")
          .innerText({ timeout: 1000 })
          .catch(() => ""),
      ),
    };
  }

  try {
    launched = await runStage("launch_browser", () => launchChromium(chromium));
    browser = launched.browser;
    page = await runStage("new_page", () => browser.newPage({ viewport: { width: 1280, height: 900 } }));

    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push(message.text());
      }
    });

    await runStage("open_login", (timeout) =>
      page.goto(joinUrl(args.url, "wp-login.php"), { waitUntil: "domcontentloaded", timeout }),
    );
    await runStage("fill_login", async (timeout) => {
      await page.fill("#user_login", args.username, { timeout });
      await page.fill("#user_pass", args.password, { timeout });
    });
    await runStage("submit_login", async (timeout) => {
      await page.click("#wp-submit", { timeout });
      await page.waitForLoadState("domcontentloaded", { timeout }).catch(() => undefined);
    });

    await runStage("open_post_editor", (timeout) =>
      page.goto(
        args.deprecationSmoke
          ? joinUrl(args.url, `wp-admin/post.php?post=${args.postId}&action=edit`)
          : joinUrl(args.url, "wp-admin/post-new.php"),
        { waitUntil: "domcontentloaded", timeout },
      ),
    );
    await runStage("wait_for_block_registry", (timeout) =>
      page.waitForFunction(
        () => window.wp && window.wp.blocks && typeof window.wp.blocks.getBlockType === "function",
        null,
        { timeout },
      ),
    );
    await runStage("wait_for_target_block", (timeout) =>
      page.waitForFunction(
        (blockName) => Boolean(window.wp.blocks.getBlockType(blockName)),
        args.blockName,
        { timeout },
      ),
    );
    await runStage("wait_for_editor_store", (timeout) =>
      page.waitForFunction(
        () =>
          window.wp &&
          window.wp.data &&
          window.wp.blocks &&
          typeof window.wp.blocks.createBlock === "function" &&
          window.wp.data.dispatch("core/block-editor") &&
          typeof window.wp.data.dispatch("core/block-editor").insertBlocks === "function" &&
          window.wp.data.dispatch("core/editor") &&
          typeof window.wp.data.dispatch("core/editor").savePost === "function",
        null,
        { timeout },
      ),
    );

    const block = await runStage("read_block_metadata", () => page.evaluate((blockName) => {
      const found = window.wp.blocks.getBlockType(blockName);
      return found
        ? {
            name: found.name,
            title: found.title,
            category: found.category,
            icon: typeof found.icon === "string" ? found.icon : typeof found.icon,
          }
        : null;
    }, args.blockName));

    const body = await runStage("read_editor_body", () => page.evaluate(() => ({
      title: document.title,
      bodyTextLength: document.body.innerText.trim().length,
      hasEditorRoot: Boolean(document.querySelector(".block-editor, .editor-styles-wrapper, .edit-post-layout")),
    })));
    let interaction = null;

    if (args.deprecationSmoke) {
      interaction = await runStage(
        "deprecated_content_migrate_save_frontend_render",
        async (timeout) => {
          const migrated = await page.evaluate(
            async ({ blockName, expectedMigratedAttributeName, expectedMigratedAttribute, expectedSerializedMarker, timeoutMs }) => {
              const waitFor = (predicate) =>
                new Promise((resolve, reject) => {
                  const started = Date.now();
                  const interval = window.setInterval(() => {
                    if (predicate()) {
                      window.clearInterval(interval);
                      resolve(true);
                    } else if (Date.now() - started > timeoutMs) {
                      window.clearInterval(interval);
                      reject(new Error("timed out waiting for deprecated block migration"));
                    }
                  }, 100);
                });

              await waitFor(() => {
                const blockEditor = window.wp.data.select("core/block-editor");
                return blockEditor && blockEditor.getBlocks().length > 0;
              });

              const editor = window.wp.data.select("core/editor");
              const blockEditor = window.wp.data.select("core/block-editor");
              const blocks = blockEditor.getBlocks();
              const target = blocks.find((item) => item.name === blockName);
              const bodyText = document.body.innerText || "";
              const serializedBeforeSave =
                typeof editor.getEditedPostContent === "function" ? editor.getEditedPostContent() : "";

              const invalidBlockUIFound = /unexpected or invalid content|attempt block recovery/i.test(bodyText);
              const migratedAttributeFound = target
                ? target.attributes && target.attributes[expectedMigratedAttributeName] === expectedMigratedAttribute
                : false;
              const serializedMigratedBlocks =
                target && window.wp.blocks && typeof window.wp.blocks.serialize === "function"
                  ? window.wp.blocks.serialize(blocks)
                  : "";

              window.wp.data.dispatch("core/editor").editPost({ content: serializedMigratedBlocks, status: "publish" });
              await window.wp.data.dispatch("core/editor").savePost();
              await waitFor(() => {
                const currentEditor = window.wp.data.select("core/editor");
                const isSaving = typeof currentEditor.isSavingPost === "function" && currentEditor.isSavingPost();
                const isAutosaving = typeof currentEditor.isAutosavingPost === "function" && currentEditor.isAutosavingPost();
                return !isSaving && !isAutosaving;
              });

              const postId = typeof editor.getCurrentPostId === "function" ? editor.getCurrentPostId() : null;
              const permalink =
                (typeof editor.getPermalink === "function" && editor.getPermalink()) ||
                (typeof editor.getEditedPostAttribute === "function" && editor.getEditedPostAttribute("link")) ||
                null;
              const didSaveFail =
                typeof editor.didPostSaveRequestFail === "function" && editor.didPostSaveRequestFail();
              const serializedAfterSave =
                typeof editor.getEditedPostContent === "function" ? editor.getEditedPostContent() : "";
              const serializedMarkerFound = expectedSerializedMarker
                ? serializedBeforeSave.includes(expectedSerializedMarker) ||
                  serializedMigratedBlocks.includes(expectedSerializedMarker) ||
                  serializedAfterSave.includes(expectedSerializedMarker)
                : true;

              return {
                targetBlockFound: Boolean(target),
                targetAttributes: target ? target.attributes : null,
                targetIsValid: target && Object.prototype.hasOwnProperty.call(target, "isValid") ? target.isValid : null,
                expectedMigratedAttributeName,
                expectedMigratedAttribute,
                expectedSerializedMarker,
                migratedAttributeFound,
                serializedMarkerFound,
                invalidBlockUIFound,
                didSaveFail,
                postId,
                permalink,
                serializedBeforeSave: serializedBeforeSave.slice(0, 1000),
                serializedMigratedBlocks: serializedMigratedBlocks.slice(0, 1000),
                serializedAfterSave: serializedAfterSave.slice(0, 1000),
              };
            },
            {
              blockName: args.blockName,
              expectedMigratedAttributeName: args.expectedMigratedAttributeName,
              expectedMigratedAttribute: args.expectedMigratedAttribute,
              expectedSerializedMarker: args.expectedSerializedMarker,
              timeoutMs: timeout,
            },
          );

          const deprecation = verifyDeprecationResult(migrated);
          const frontendUrl = migrated.permalink || postUrl(args.url, migrated.postId);
          const wrapperClass = defaultBlockClassName(args.blockName);
          await page.goto(frontendUrl, { waitUntil: "domcontentloaded", timeout });
          const wrapper = page.locator(`.${wrapperClass}`).first();
          const wrapperText = await wrapper.innerText({ timeout });
          const frontendRender = verifyFrontendRender(
            wrapperText, `.${wrapperClass}`, args.expectedMigratedText,
          );

          return {
            ...migrated,
            ...deprecation,
            frontendTitle: await page.title(),
            frontendUrl: page.url(),
            ...frontendRender,
          };
        },
        45000,
      );
    } else if (args.insertRenderSmoke) {
      interaction = await runStage(
        "insert_save_frontend_render",
        async (timeout) => {
          const inserted = await page.evaluate(
            async ({ blockName, timeoutMs }) => {
              const waitFor = (predicate) =>
                new Promise((resolve, reject) => {
                  const started = Date.now();
                  const interval = window.setInterval(() => {
                    if (predicate()) {
                      window.clearInterval(interval);
                      resolve(true);
                    } else if (Date.now() - started > timeoutMs) {
                      window.clearInterval(interval);
                      reject(new Error("timed out waiting for editor save"));
                    }
                  }, 100);
                });

              const title = `Runtime Block Smoke ${Date.now()}`;
              const block = window.wp.blocks.createBlock(blockName);
              window.wp.data.dispatch("core/block-editor").insertBlocks(block);
              window.wp.data.dispatch("core/editor").editPost({ title, status: "publish" });
              await window.wp.data.dispatch("core/editor").savePost();
              await waitFor(() => {
                const editor = window.wp.data.select("core/editor");
                const isSaving = typeof editor.isSavingPost === "function" && editor.isSavingPost();
                const isAutosaving = typeof editor.isAutosavingPost === "function" && editor.isAutosavingPost();
                return !isSaving && !isAutosaving;
              });

              const editor = window.wp.data.select("core/editor");
              const blockEditor = window.wp.data.select("core/block-editor");
              const postId = typeof editor.getCurrentPostId === "function" ? editor.getCurrentPostId() : null;
              const permalink =
                (typeof editor.getPermalink === "function" && editor.getPermalink()) ||
                (typeof editor.getEditedPostAttribute === "function" && editor.getEditedPostAttribute("link")) ||
                null;
              const didSaveFail =
                typeof editor.didPostSaveRequestFail === "function" && editor.didPostSaveRequestFail();
              const blocks = typeof blockEditor.getBlocks === "function" ? blockEditor.getBlocks() : [];

              return {
                didSaveFail,
                inserted: blocks.some((item) => item.name === blockName),
                permalink,
                postId,
                savedTitle:
                  typeof editor.getEditedPostAttribute === "function"
                    ? editor.getEditedPostAttribute("title")
                    : title,
                serializedBlockCount: blocks.length,
                title,
              };
            },
            { blockName: args.blockName, timeoutMs: timeout },
          );

          if (inserted.didSaveFail) {
            throw new Error("editor save request failed");
          }
          if (!inserted.inserted) {
            throw new Error(`inserted block not found in editor store: ${args.blockName}`);
          }
          if (!inserted.postId) {
            throw new Error("saved post id was not available");
          }

          const frontendUrl = inserted.permalink || postUrl(args.url, inserted.postId);
          const wrapperClass = defaultBlockClassName(args.blockName);
          await page.goto(frontendUrl, { waitUntil: "domcontentloaded", timeout });
          const wrapper = page.locator(args.expectedFrontendSelector).first();
          const wrapperText = await wrapper.innerText({ timeout });
          const frontendRender = verifyFrontendRender(
            wrapperText,
            args.expectedFrontendSelector,
            args.expectedFrontendText,
          );
          const frontendInteractivity = args.interactivitySmoke
            ? await verifyFrontendInteractivity(page, wrapperClass, timeout)
            : null;

          return {
            ...inserted,
            frontendTitle: await page.title(),
            frontendUrl: page.url(),
            ...frontendRender,
            interactivity: frontendInteractivity,
          };
        },
        45000,
      );
    }

    const errors = [];
    if (!block) {
      errors.push(`block not available in editor registry: ${args.blockName}`);
    }
    if (!body.hasEditorRoot) {
      errors.push("block editor root was not found");
    }
    if (pageErrors.length > 0) {
      errors.push(`page errors: ${pageErrors.join(" | ")}`);
    }
    if (consoleErrors.length > 0) {
      errors.push(`console errors: ${consoleErrors.join(" | ")}`);
    }
    if (args.insertRenderSmoke && !interaction) {
      errors.push("insert/render smoke did not run");
    }
    if (args.deprecationSmoke && !interaction) {
      errors.push("deprecation smoke did not run");
    }

    const payload = {
      status: errors.length === 0 ? "pass" : "fail",
      browser: launched.label,
      url: args.url,
      blockName: args.blockName,
      block,
      body,
      insertRenderSmoke: args.insertRenderSmoke,
      interactivitySmoke: args.interactivitySmoke,
      deprecationSmoke: args.deprecationSmoke,
      interaction,
      stages,
      pageErrors,
      consoleErrors,
      errors,
    };
    console.log(JSON.stringify(payload, null, 2));
    process.exitCode = errors.length === 0 ? 0 : 1;
  } catch (error) {
    const payload = {
      status: "fail",
      browser: launched.label,
      url: args.url,
      blockName: args.blockName,
      block: null,
      body: await pageSnapshot(),
      insertRenderSmoke: args.insertRenderSmoke,
      interactivitySmoke: args.interactivitySmoke,
      deprecationSmoke: args.deprecationSmoke,
      interaction: null,
      stages,
      pageErrors,
      consoleErrors,
      errors: [truncate(errorMessage(error))],
    };
    console.log(JSON.stringify(payload, null, 2));
    process.exitCode = 1;
  } finally {
    if (browser) {
      await browser.close().catch(() => undefined);
    }
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
} else {
  module.exports = {
    defaultBlockClassName,
    verifyFrontendRender,
    verifyFrontendInteractivity,
    verifyInteractivityResult,
    verifyDeprecationResult,
  };
}
