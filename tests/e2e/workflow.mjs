/** Run against a disposable local test server; never point this at personal source files. */
import assert from "node:assert/strict";
import {createRequire} from "node:module";
import path from "node:path";
import fs from "node:fs/promises";
import {spawn} from "node:child_process";

const require = createRequire(import.meta.url);
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const port = Number(process.env.FILE_SORTER_TEST_PORT || 8877);
const base = `http://127.0.0.1:${port}`;
await fs.mkdir(".test-artifacts", {recursive: true});
const workspace = await fs.mkdtemp(path.resolve(".test-artifacts/browser-run-"));
const root = path.join(workspace, "files");
await fs.mkdir(path.join(root, "inbox"), {recursive: true});
await fs.writeFile(path.join(root, "inbox", "photo.JPG"), "photo fixture");
await fs.writeFile(path.join(root, "inbox", "report.pdf"), "pdf fixture");
const serverCode = "import sys,json,os; sys.path[:0]=json.loads(os.environ.get('FILE_SORTER_TEST_IMPORT_PATHS','[]')); from pathlib import Path; import uvicorn; from file_sorter.app import create_app; uvicorn.run(create_app([sys.argv[1]],Path(sys.argv[2]),int(sys.argv[3])),host='127.0.0.1',port=int(sys.argv[3]))";
const server = spawn(process.env.PYTHON || "python", ["-u", "-c", serverCode, root, path.join(workspace, "state"), String(port)], {windowsHide: true, stdio: "pipe"});
let serverLog = "";
server.stderr.on("data", chunk => {serverLog += chunk;});
server.on("error", error => {serverLog += error.message;});
for (let attempt = 0; attempt < 100; attempt++) {
  try {if ((await fetch(`${base}/api/health`)).ok) break;} catch {}
  if (attempt === 99 || server.exitCode !== null) {server.kill(); throw new Error(`Test server failed: ${serverLog}`);}
  await new Promise(resolve => setTimeout(resolve, 100));
}
const browser = await chromium.launch({headless: true, channel: process.env.BROWSER_CHANNEL || "msedge"});
const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
const errors = [];
page.on("pageerror", error => errors.push(error.message));

try {
  await page.goto(base);
  await page.getByRole("heading", {name: "A place for everything."}).waitFor();
  await page.locator(".rule").first().waitFor();
  await page.getByLabel("Source folder", {exact: true}).fill(path.join(root, "inbox"));
  await page.getByLabel("File extensions", {exact: true}).first().fill("jpg, pdf");
  await page.getByLabel("Destination folder", {exact: true}).first().fill(path.join(root, "sorted"));
  await page.getByRole("button", {name: "Save rules", exact: true}).click();
  await page.getByText("Rules saved. They will be here next time.").waitFor();
  await page.locator("#browse-source").click();
  await page.getByRole("dialog").waitFor();
  await page.getByRole("button", {name: `▱  ${root}`, exact: true}).click();
  await page.getByRole("button", {name: "▱  inbox", exact: true}).click();
  await page.getByRole("button", {name: "Use this folder", exact: true}).click();
  assert.equal(await page.locator("#source").inputValue(), path.join(root, "inbox"));
  await page.getByRole("button", {name: "Preview files"}).click();
  await page.getByRole("heading", {name: "Everything, before it moves."}).waitFor();
  assert.match(await page.locator("#progress-label").textContent(), /2 to move/);
  assert.equal(await fs.readFile(path.join(root, "inbox", "photo.JPG"), "utf8"), "photo fixture");
  await page.screenshot({path: ".test-artifacts/desktop-preview.png", fullPage: true});
  // Editing after preview must disable Sort until the next preview.
  await page.locator("#recursive").check();
  assert.equal(await page.locator("#sort").isDisabled(), true);
  await page.getByRole("button", {name: "Preview files"}).click();
  await page.waitForFunction(() => !document.getElementById("sort").disabled);
  await page.getByRole("button", {name: "Sort files", exact: true}).click();
  await page.getByRole("heading", {name: process.platform === "win32" ? "completed" : "completed with errors", exact: true}).waitFor();
  assert.equal(await fs.readFile(path.join(root, "sorted", "photo.JPG"), "utf8"), "photo fixture");
  assert.equal(await fs.readFile(path.join(root, "sorted", "report.pdf"), "utf8"), "pdf fixture");
  if (process.platform === "win32") await assert.rejects(fs.access(path.join(root, "inbox", "photo.JPG")));
  await page.screenshot({path: ".test-artifacts/desktop-results.png", fullPage: true});
  await page.setViewportSize({width: 390, height: 844});
  await page.screenshot({path: ".test-artifacts/mobile-results.png", fullPage: true});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.reload();
  await page.locator(".rule-extensions").first().waitFor();
  assert.equal(await page.locator(".rule-extensions").first().inputValue(), "jpg, pdf");
  await page.getByRole("button", {name: "View details →"}).first().waitFor();
  assert.deepEqual(errors, []);
  console.log("Browser workflow passed: folder browsing, save, preview, invalidation, sort, content integrity, history, responsive layout, persistence, and no JavaScript errors.");
} finally {
  await browser.close();
  server.kill();
}
