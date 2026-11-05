const form = document.querySelector("#ask-form");
const banner = document.querySelector("#banner");
const freshness = document.querySelector("#freshness");
const hint = document.querySelector("#hint");
const summary = document.querySelector("#summary");
const out = document.querySelector("#out");
const scans = document.querySelector("#scans");
const events = document.querySelector("#events");
const patrons = document.querySelector("#patrons");
const patronSection = document.querySelector("#patron-section");
const assets = document.querySelector("#assets");
const assetSection = document.querySelector("#asset-section");
const refreshButton = document.querySelector("#refresh");

let timer = 0;
let requestId = 0;

form.addEventListener("submit", (event) => {
  event.preventDefault();
  load();
});

refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  await fetch("/api/refresh", { method: "POST" });
  load();
});

function text(tag, value, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value || "";
  return node;
}

function statusClass(status) {
  if (status === "Checked Out" || (status || "").startsWith("Assigned")) return "status out";
  if (["Damaged", "Damaged - Stick Drift", "Lost/Missing", "In Repairs"].includes(status)) return "status bad";
  if (status === "Available" || status === "Available at Information Desk") return "status ok";
  return "status";
}

function table(columns, rows) {
  if (!rows.length) return text("p", "Nothing in this window.", "empty");
  const wrap = document.createElement("table");
  const head = document.createElement("tr");
  columns.forEach((column) => head.append(text("th", column)));
  const thead = document.createElement("thead");
  thead.append(head);
  const body = document.createElement("tbody");
  rows.forEach((cells) => {
    const row = document.createElement("tr");
    cells.forEach((cell) => {
      const td = document.createElement("td");
      if (cell instanceof Node) td.append(cell);
      else td.textContent = cell || "";
      row.append(td);
    });
    body.append(row);
  });
  wrap.append(thead, body);
  return wrap;
}

function assetCell(id, name) {
  const node = document.createElement("div");
  node.append(text("span", id, "asset-id"));
  if (name) node.append(text("span", name, "sub"));
  return node;
}

function render(data) {
  freshness.textContent = data.source === "sample"
    ? "Sample records. Add the AssetPanda account to see the live desk."
    : `Live AssetPanda, read ${data.built_at || "just now"}.`;
  if (data.indexing) {
    freshness.textContent += ` Still reading ${data.loaded} of ${data.total}.`;
  }
  refreshButton.disabled = Boolean(data.indexing) || data.source === "sample";

  banner.hidden = !data.error;
  banner.textContent = data.error || "";
  hint.textContent = data.hint || "";

  const summaryItems = [
    [data.summary.checked_out, "Checked out"],
    [data.summary.assigned, "Assigned"],
    [data.summary.trouble, "Damaged, lost, or in repair"],
    [data.summary.patron_today, "Patron loans today"],
    [data.summary.moves, "Event moves"],
    [data.summary.scans, "Items scanned"],
  ];
  summary.replaceChildren();
  summaryItems.forEach(([count, label]) => {
    const block = document.createElement("div");
    block.append(text("strong", String(count)), text("span", label));
    summary.append(block);
  });

  out.replaceChildren(table(
    ["Status", "Asset", "With", "Where"],
    data.out_now.map((asset) => [
      text("span", asset.status, statusClass(asset.status)),
      assetCell(asset.asset_id, asset.name),
      asset.who,
      asset.place,
    ]),
  ));

  scans.replaceChildren();
  const scanSection = scans.closest("section");
  scanSection.hidden = Boolean(data.query) && !data.scans.length;
  if (!data.scans.length) {
    scans.append(text("p", "No scans in this window.", "empty"));
  } else {
    data.scans.forEach((session) => {
      const details = document.createElement("details");
      const row = document.createElement("summary");
      row.className = "session";
      row.append(text("span", session.who || "Unknown"));
      row.append(text("span", session.when_label));
      row.append(text("span", session.place || session.condition || session.action));
      row.append(text("span", String(session.count), "count"));
      details.append(row);
      const list = document.createElement("ul");
      list.className = "assets-inline";
      session.assets.forEach((asset) => {
        const item = document.createElement("li");
        item.textContent = [asset.asset_id, asset.asset_name, asset.condition, asset.place].filter(Boolean).join(" · ");
        list.append(item);
      });
      details.append(list);
      scans.append(details);
    });
  }

  patronSection.hidden = Boolean(data.query);
  patrons.replaceChildren(table(
    ["When", "Asset", "Employee", "Patron", "Reason", "Back"],
    (data.patrons || []).map((item) => [
      item.when_label,
      assetCell(item.asset_id, item.asset_name),
      item.who,
      item.patron,
      item.reason,
      item.returned_label,
    ]),
  ));

  events.replaceChildren(table(
    ["When", "For", "Asset", "What", "Who", "Where", "Back"],
    data.events.map((item) => [
      item.when_label,
      item.reason,
      assetCell(item.asset_id, item.asset_name),
      item.action,
      item.who || item.logged_by,
      item.place,
      item.returned_label,
    ]),
  ));

  const showAssets = Boolean(data.query) && data.assets.length > 0;
  assetSection.hidden = !showAssets;
  if (showAssets) {
    assets.replaceChildren(table(
      ["Asset", "Status", "With", "Where"],
      data.assets.map((asset) => [
        assetCell(asset.asset_id, asset.name || asset.category),
        text("span", asset.status, statusClass(asset.status)),
        asset.who,
        asset.place,
      ]),
    ));
  }
}

async function load() {
  const current = ++requestId;
  window.clearTimeout(timer);
  const params = new URLSearchParams(new FormData(form));
  const response = await fetch(`/api/desk?${params}`);
  if (current !== requestId) return;
  const data = await response.json();
  render(data);
  if (data.indexing) timer = window.setTimeout(load, 2000);
}

load();
