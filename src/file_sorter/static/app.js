/** Browser workflow. File paths and rule text are always inserted as text, never HTML. */
import {requestJson, bootstrapSession} from "./api.js";

const $ = (id) => document.getElementById(id);
let revision = 0, dirty = false, preview = null, view = null, offset = 0, historyOffset = 0;
let generation = 0, activeJob = null, folderTarget = null, folder = null, folderParent = null;
let pageItems = [], pageTotal = 0, previewTimer = null, pollTimer = null;
const pageSize = 100;

function notify(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
  $("notice").hidden = !message;
}

async function attempt(action) {
  document.querySelectorAll(".field-error").forEach(node => node.remove());
  document.querySelectorAll('[aria-invalid="true"]').forEach(node => node.removeAttribute("aria-invalid"));
  try { await action(); } catch (error) {
    notify(error.message, true);
    const selectors = {source: "#source", extensions: ".rule-extensions", destination: ".rule-destination", template: ".rule-template"};
    const input = selectors[error.field] && document.querySelector(selectors[error.field]);
    if (input) {
      input.setAttribute("aria-invalid", "true");
      input.parentElement.append(element("p", "field-error", error.message));
      input.focus();
    }
  }
}

function invalidate() {
  generation++;
  preview = null;
  clearTimeout(previewTimer);
  $("sort").disabled = true;
  $("move-count").textContent = "—";
  $("byte-count").textContent = "—";
  if (view?.kind === "previews") $("progress-label").textContent = "Settings changed. Create a new preview before sorting.";
}

function changedRules() {
  dirty = true;
  $("save-state").textContent = "Unsaved changes";
  invalidate();
  $("rule-count").textContent = document.querySelectorAll(".rule-enabled:checked").length;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function field(label, input) {
  const wrapper = element("div");
  const caption = element("label", "", label);
  caption.htmlFor = input.id;
  wrapper.append(caption, input);
  return wrapper;
}

function addRule(rule = {}) {
  const id = rule.id || crypto.randomUUID();
  const row = element("article", "rule");
  row.dataset.id = id;
  const top = element("div", "rule-top");
  const enabled = element("input", "rule-enabled");
  enabled.type = "checkbox"; enabled.checked = rule.enabled ?? true;
  enabled.setAttribute("aria-label", "Enable this rule");
  const label = element("input", "rule-label");
  label.value = rule.label || "New rule"; label.maxLength = 100;
  label.setAttribute("aria-label", "Rule name");
  const remove = element("button", "remove", "Remove");
  remove.addEventListener("click", () => {row.remove(); changedRules();});
  top.append(enabled, label, remove);
  const grid = element("div", "rule-grid");
  const extensions = element("input", "rule-extensions");
  extensions.id = `extensions-${id}`; extensions.value = rule.extensions || "";
  extensions.placeholder = "jpg, jpeg, png";
  const destination = element("input", "rule-destination");
  destination.id = `destination-${id}`; destination.value = rule.destination || "";
  destination.placeholder = "Full destination path";
  const destinationField = field("Destination folder", destination);
  const inputAction = element("div", "input-action");
  const browse = element("button", "secondary", "Browse");
  browse.addEventListener("click", () => attempt(() => browseFolder(destination)));
  inputAction.append(destination, browse); destinationField.append(inputAction);
  grid.append(field("File extensions", extensions), destinationField);
  const details = element("details");
  const summary = element("summary", "", "Optional renaming");
  const template = element("input", "rule-template");
  template.id = `template-${id}`; template.value = rule.template || "";
  template.placeholder = "Leave blank to keep original filenames";
  details.append(summary, field("Filename template", template), element("p", "hint", "Use {stem}, {date}, {counter}. The extension is kept automatically."));
  row.append(top, grid, details);
  row.addEventListener("input", changedRules);
  $("rules").append(row);
}

function collectRules() {
  return [...document.querySelectorAll(".rule")].map(row => ({id: row.dataset.id,
    label: row.querySelector(".rule-label").value.trim(), enabled: row.querySelector(".rule-enabled").checked,
    destination: row.querySelector(".rule-destination").value.trim(), extensions: row.querySelector(".rule-extensions").value,
    template: row.querySelector(".rule-template").value}));
}

async function saveRules() {
  const snapshot = collectRules();
  const result = await requestJson("/api/rules", "PUT", {revision, rules: snapshot});
  revision = result.revision; dirty = JSON.stringify(snapshot) !== JSON.stringify(collectRules());
  $("save-state").textContent = dirty ? "Unsaved changes" : "Saved";
  invalidate();
  notify("Rules saved. They will be here next time.");
}

async function browseFolder(target) {
  folderTarget = target;
  await loadFolder(null);
  $("folder-dialog").showModal();
}

async function loadFolder(path) {
  const data = await requestJson(`/api/folders${path ? `?path=${encodeURIComponent(path)}` : ""}`);
  folder = data.path; folderParent = data.parent;
  $("folder-path").textContent = folder || "Folders permitted when the application was started";
  $("folder-up").disabled = !folderParent;
  $("folder-select").disabled = !folder;
  $("folder-list").replaceChildren();
  for (const item of data.directories) {
    const button = element("button", "", `▱  ${item.name}`);
    button.addEventListener("click", () => attempt(() => loadFolder(item.path)));
    $("folder-list").append(button);
  }
  if (!data.directories.length) $("folder-list").append(element("p", "", "No subfolders. You can select this folder."));
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024, i = 0;
  while (value >= 1024 && i < units.length - 1) {value /= 1024; i++;}
  return `${value.toFixed(1)} ${units[i]}`;
}

async function requestPreview() {
  $("preview").disabled = true;
  try {
    if (dirty) await saveRules();
    if (dirty) throw new Error("Rules changed while saving. Preview again to save the latest edits.");
    invalidate();
    const ticket = generation;
    const result = await requestJson("/api/previews", "POST", {source: $("source").value.trim(),
      recursive: $("recursive").checked, include_hidden: $("include-hidden").checked, collision: $("collision").value});
    if (ticket !== generation) return;
    offset = 0; view = {kind: "previews", id: result.id};
    $("review-title").textContent = "Building your preview…";
    $("progress-label").textContent = "Scanning files. No files are being changed.";
    await pollStatus(ticket);
  } finally {$("preview").disabled = false;}
}

function renderItems() {
  $("items").replaceChildren();
  const filtered = pageItems.filter(item => $("filter").value === "all" || item.action === $("filter").value || (item.phase === "error" && $("filter").value === "error"));
  for (const item of filtered) {
    const row = element("tr");
    const source = element("td");
    source.append(element("strong", "", item.source.split(/[\\/]/).pop()), element("small", "", item.source));
    const destination = element("td", "", item.destination || "Stays in place");
    if (item.create_directory && view?.kind === "previews") destination.append(element("small", "", "Destination folder will be created"));
    if (item.temporary && item.phase === "needs_review") destination.append(element("small", "", `Temporary file: ${item.temporary}`));
    const status = element("td");
    const tag = view?.kind === "jobs" ? item.phase : item.action;
    status.append(element("span", `tag ${tag}`, tag.replaceAll("_", " ")), element("small", "", item.reason));
    row.append(source, destination, element("td", "", item.rule || "—"), status);
    $("items").append(row);
  }
  $("empty").hidden = pageItems.length > 0;
  $("table-wrap").hidden = pageItems.length === 0;
  $("pagination").hidden = pageTotal <= pageSize;
  $("page-label").textContent = `${offset + 1}–${Math.min(offset + pageSize, pageTotal)} of ${pageTotal}`;
  $("previous").disabled = offset === 0;
  $("next").disabled = offset + pageSize >= pageTotal;
}

async function pollStatus(ticket) {
  if (!view) return;
  const current = {...view};
  const currentOffset = offset;
  const data = await requestJson(`/api/${current.kind}/${current.id}?offset=${offset}&limit=${pageSize}`);
  if (!view || current.id !== view.id || currentOffset !== offset || (current.kind === "previews" && ticket !== generation)) return;
  pageItems = data.items || []; pageTotal = data.total || 0;
  renderItems();
  const running = ["scanning", "queued", "running"].includes(data.state);
  if (current.kind === "previews") {
    $("progress").hidden = true;
    $("cancel").hidden = true;
    if (data.state === "ready") {
      preview = data;
      $("review-title").textContent = "Everything, before it moves.";
      $("progress-label").textContent = `${data.counts.move || 0} to move · ${data.counts.skip || 0} skipped · ${data.counts.error || 0} errors`;
      $("move-count").textContent = data.counts.move || 0;
      $("byte-count").textContent = formatBytes(data.bytes);
      $("sort").disabled = !data.counts.move || !!activeJob;
      clearTimeout(previewTimer);
      previewTimer = setTimeout(() => {invalidate(); notify("Preview expired. Create a new preview before sorting.");}, Math.max(0, data.expires * 1000 - Date.now()));
    } else if (!running) {invalidate(); notify(data.error || "Preview expired. Please preview again.", true);}
  } else {
    $("review-title").textContent = data.state.replaceAll("_", " ");
    $("progress-label").textContent = `${data.processed}/${data.total} checked · ${data.moved} moved · ${data.skipped} skipped · ${data.errors} errors · ${data.retained} copies with original retained${data.error ? ` · ${data.error}` : ""}`;
    $("progress").hidden = false; $("progress").max = Math.max(data.total, 1); $("progress").value = data.processed;
    $("cancel").hidden = !running;
    if (!running) {
      if (activeJob === current.id) activeJob = null;
      notify(data.state === "completed" ? `Sort finished. ${data.moved} files moved.` : `Sort ${data.state.replaceAll("_", " ")}. Review the per-file results.`, data.state !== "completed");
      await loadHistory();
    }
  }
  clearTimeout(pollTimer);
  if (running) pollTimer = setTimeout(() => attempt(() => pollStatus(ticket)), 700);
}

async function startSort() {
  if (!preview) return;
  $("sort").disabled = true;
  const selected = preview;
  const job = await requestJson("/api/jobs", "POST", {preview_id: selected.id, idempotency_key: selected.id});
  activeJob = job.id;
  invalidate(); offset = 0; view = {kind: "jobs", id: job.id};
  notify("Sorting started. You can stop after the current file; completed moves will stay completed.");
  await pollStatus(generation);
}

async function loadHistory() {
  const history = await requestJson(`/api/jobs?offset=${historyOffset}&limit=10`);
  $("history").replaceChildren();
  for (const job of history.items) {
    const row = element("div", "history-row");
    const label = element("div", "", job.state.replaceAll("_", " "));
    label.append(element("small", "", `${new Date(job.created * 1000).toLocaleString()} · ${job.moved} moved · ${job.errors} errors · ${job.retained} retained`));
    const button = element("button", "text-button", "View details →");
    button.addEventListener("click", () => attempt(async () => {offset = 0; view = {kind: "jobs", id: job.id}; await pollStatus(generation); $("review-title").scrollIntoView({block: "center"});}));
    row.append(label, button); $("history").append(row);
    if (["queued", "running"].includes(job.state)) activeJob = job.id;
  }
  if (!history.total) $("history").append(element("p", "muted", "No sorts yet. Your activity will appear here."));
  $("history-previous").disabled = historyOffset === 0;
  $("history-next").disabled = historyOffset + 10 >= history.total;
  $("history-page").textContent = history.total ? `${historyOffset + 1}–${Math.min(historyOffset + 10, history.total)} of ${history.total}` : "";
}

async function initialize() {
  await bootstrapSession();
  const config = await requestJson("/api/rules"); revision = config.revision;
  config.rules.forEach(addRule);
  $("rule-count").textContent = config.rules.filter(rule => rule.enabled).length;
  if (!config.rules.length) {addRule({label: "Images"}); changedRules();}
  for (const id of ["source", "recursive", "include-hidden", "collision"]) $(id).addEventListener("input", invalidate);
  $("browse-source").addEventListener("click", () => attempt(() => browseFolder($("source"))));
  $("add-rule").addEventListener("click", () => {addRule(); changedRules();});
  $("save-rules").addEventListener("click", () => attempt(saveRules));
  $("preview").addEventListener("click", () => attempt(requestPreview));
  $("sort").addEventListener("click", () => attempt(startSort));
  $("filter").addEventListener("change", renderItems);
  $("cancel").addEventListener("click", () => attempt(async () => {await requestJson(`/api/jobs/${view.id}/cancel`, "POST", {}); notify("Stop requested. The current file will finish safely.");}));
  $("previous").addEventListener("click", () => attempt(async () => {offset = Math.max(0, offset-pageSize); await pollStatus(generation);}));
  $("next").addEventListener("click", () => attempt(async () => {offset += pageSize; await pollStatus(generation);}));
  $("folder-roots").addEventListener("click", () => attempt(() => loadFolder(null)));
  $("folder-up").addEventListener("click", () => attempt(() => loadFolder(folderParent)));
  $("folder-select").addEventListener("click", () => {folderTarget.value = folder; folderTarget.dispatchEvent(new Event("input", {bubbles: true})); $("folder-dialog").close();});
  $("refresh-history").addEventListener("click", () => attempt(loadHistory));
  $("history-previous").addEventListener("click", () => attempt(async () => {historyOffset = Math.max(0, historyOffset-10); await loadHistory();}));
  $("history-next").addEventListener("click", () => attempt(async () => {historyOffset += 10; await loadHistory();}));
  await loadHistory();
  if (activeJob) {view = {kind: "jobs", id: activeJob}; await pollStatus(generation);}
}

attempt(initialize);
