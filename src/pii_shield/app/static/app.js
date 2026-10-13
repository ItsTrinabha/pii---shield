/* Cloak UI — vanilla JS, no external requests. All document text is untrusted: everything goes through esc(). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtN = (n) => (n == null ? "—" : Number(n).toLocaleString());
const pct = (v, d = 1) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
const bytes = (b) => (b == null ? "" : b < 1024 ? b + " B" : b < 1048576 ? (b / 1024).toFixed(0) + " KB" : (b / 1048576).toFixed(1) + " MB");
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const slug = (s) => String(s).replace(/[^A-Za-z0-9]+/g, "-");

const TYPE = {
  PERSON: ["Person", "#0a6fe0", "#e3f0ff"], EMAIL: ["Email", "#5e5ce6", "#ecebff"], PHONE: ["Phone", "#13879e", "#dff5f9"],
  EMPLOYEE_ID: ["Employee ID", "#1f8a4c", "#e1f5e8"], SSN: ["SSN", "#d62c22", "#ffe6e4"], PASSPORT: ["Passport", "#c81e55", "#ffe4ec"],
  TAX_ID: ["Tax ID", "#b25f00", "#fff0d9"], DATE_OF_BIRTH: ["Date of birth", "#8e3fd0", "#f3e8ff"], ADDRESS: ["Address", "#7d5f36", "#f5eee3"],
  FINANCIAL_ACCOUNT: ["Financial acct", "#a8520a", "#ffecd9"], IP_ADDRESS: ["IP address", "#1f7fb0", "#e0f1fb"],
  GOV_ID: ["National ID", "#b0123f", "#ffe3ea"], TECH_ID: ["Device ID", "#2a6f8f", "#e2f2f8"], SECRET: ["Secret", "#4b3fb0", "#ebe9ff"], GENERIC_ID: ["Other ID", "#5b6470", "#eef0f3"], UNCLASSIFIED: ["Unclassified", "#5f6e82", "#edf0f4"],
};
const tinfo = (t) => { const v = TYPE[t] || [String(t || "?").replace(/_/g, " "), "#5f6e82", "#edf0f4"]; return { n: v[0], c: v[1], bg: v[2] }; };
const tpill = (t) => { const i = tinfo(t); return `<span class="tp" style="color:${i.c};background:${i.bg}">${esc(i.n)}</span>`; };
const CONF = { PUBLIC: ["#1b8f4c", 1], INTERNAL: ["#0a6fe0", 2], CONFIDENTIAL: ["#b86200", 3], RESTRICTED: ["#cf2a20", 4] };
const STATUS_TEXT = {
  PASS: "Verified clean and released for LLM use.",
  REVIEW: "Sanitised. A few items need a person's sign-off before release.",
  BLOCKED: "Not released. The gateway could not verify this document.",
};
const ICON = {
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 15V3.5m0 0L7.5 8M12 3.5L16.5 8"/><path d="M4 14.5v3.5A2 2 0 006 20h12a2 2 0 002-2v-3.5"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3.5H7a2 2 0 00-2 2v13a2 2 0 002 2h10a2 2 0 002-2V8.5z"/><path d="M14 3.5v5h5"/></svg>',
  down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11m0 0l-4.5-4.5M12 15l4.5-4.5M5 20h14"/></svg>',
  ok: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.8"/></svg>',
  warn: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4m0 3.5v.01M10.3 4.2L2.8 17.5A2 2 0 004.5 20.5h15a2 2 0 001.7-3L13.7 4.2a2 2 0 00-3.4 0z"/></svg>',
  chev: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>',
  down2: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg>',
  eye: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/></svg>',
};

/* ------------------------------------------------------------------------------------------------ state + api */
const S = { docs: [], cur: null, view: "scan", focus: null, detail: {}, blocks: {}, rblocks: {}, deep: false, queue: [], busy: false,
  review: { mode: null, zoom: 1, tab: "hits", doc: null }, audit: { tab: "findings", q: "", types: new Set(), sort: ["id", 1], page: 0, doc: null } };

function csrf() { const m = document.cookie.match(/(?:^|;\s*)pii_csrf=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; }
async function api(path, opts = {}) {
  const o = { ...opts, headers: { ...(opts.headers || {}) } };
  if (o.method && o.method !== "GET") o.headers["x-csrf-token"] = csrf();
  const r = await fetch(path, o);
  const body = (r.headers.get("content-type") || "").includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error((body && body.error) || `Request failed (${r.status})`);
  return body;
}
const summary = (id) => S.docs.find((d) => d.id === id);
async function detail(id) { return (S.detail[id] = S.detail[id] || (await api(`/api/docs/${id}`))); }
async function blocks(id) { return (S.blocks[id] = S.blocks[id] || (await api(`/api/docs/${id}/blocks`))); }
function upsert(doc) {
  const i = S.docs.findIndex((d) => d.id === doc.id);
  if (i >= 0) S.docs[i] = doc; else S.docs.unshift(doc);
  delete S.detail[doc.id];
}

/* ------------------------------------------------------------------------------------------------ ui helpers */
function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = `toast glass ${kind}`;
  t.innerHTML = `<span>${esc(msg)}</span>`;
  $("#toasts").appendChild(t);
  setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 320); }, kind === "err" ? 6000 : 3600);
}
function animate(root) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    $$(".ring .val", root).forEach((c) => { c.style.strokeDashoffset = c.dataset.to; });
    $$("[data-w]", root).forEach((el) => { el.style.width = el.dataset.w; });
    $$("[data-h]", root).forEach((el) => { el.style.height = el.dataset.h; });
  }));
  $$("[data-count]", root).forEach((el) => {
    const to = parseFloat(el.dataset.count), dec = +(el.dataset.dec || 0), t0 = performance.now();
    const step = (t) => {
      const p = Math.min(1, (t - t0) / 950), e = 1 - Math.pow(1 - p, 3);
      el.textContent = (to * e).toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec });
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
  segs(root);
}
function segs(root = document) {
  $$(".seg", root).forEach((sg) => {
    const on = $("button.on", sg), th = $(".thumb", sg);
    if (on && th) { th.style.left = on.offsetLeft + "px"; th.style.width = on.offsetWidth + "px"; }
  });
}
function tabs() {
  const on = $(`#tabs a[data-v="${S.view}"]`), th = $("#tabs .thumb");
  $$("#tabs a").forEach((a) => {
    a.classList.toggle("on", a === on);
    a.classList.toggle("off", a.dataset.v !== "scan" && !S.cur);
    a.href = `#/${a.dataset.v}${S.cur ? "/" + S.cur : ""}`;
  });
  if (on) { th.style.width = on.offsetWidth + "px"; th.style.transform = `translateX(${on.offsetLeft - 4}px)`; }
}
const cnt = (v, dec = 0) => `<span data-count="${v ?? 0}" data-dec="${dec}">0</span>`;
function ring(v, label, color, sub = "") {
  const C = 2 * Math.PI * 45, val = v == null ? 0 : Math.max(0, Math.min(1, v));
  return `<div class="ring"><div class="wrap"><svg viewBox="0 0 108 108"><circle class="trk" cx="54" cy="54" r="45"/>
    <circle class="val" cx="54" cy="54" r="45" stroke="${color}" stroke-dasharray="${C}" stroke-dashoffset="${C}" data-to="${C * (1 - val)}"/></svg>
    <div class="num"><span>${v == null ? "—" : `${cnt((val * 100).toFixed(1), 1)}<small>%</small>`}</span></div></div><label>${esc(label)}</label>${sub ? `<div class="ci">${esc(sub)}</div>` : ""}</div>`;
}
const fileIcon = (type, lg = false) => { const t = String(type || "").toLowerCase(); return `<div class="fi ${esc(t)} ${lg ? "lg" : ""}">${esc(t.toUpperCase())}</div>`; };
function emptyState(title, text, cta = true) {
  return `<div class="view"><div class="empty glass"><div class="ico">${ICON.doc}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>
    ${cta ? `<a class="btn primary" href="#/scan">${ICON.upload}Scan a document</a>` : ""}</div></div>`;
}
function tokenHTML(text) {
  return esc(text).replace(/\[([A-Z]+(?:_[A-Z]+)*)_(\d+)\]/g, (m, t) => { const i = tinfo(t); return `<span class="tok" style="--tc:${i.c}" data-tip="${esc(i.n)} · redacted">${m}</span>`; });
}
function blockHTML(b, reveal = false) {
  if (b.hidden && !reveal) return `<em>Hidden: this block still contains residual PII. Hold the eye button to inspect it.</em>`;
  if (!reveal) return tokenHTML(b.text);
  const t = b.text, spans = (b.spans || []).slice().sort((a, c) => a[0] - c[0]);
  let out = "", pos = 0;
  for (const [s, e, typ, tok, cf] of spans) {
    if (s < pos) continue;
    const i = tinfo(typ);
    out += esc(t.slice(pos, s)) + `<mark class="pii" style="background:${i.bg};color:${i.c}" data-tip="${esc(i.n)} · ${esc(tok)} · confidence ${cf}">${esc(t.slice(s, e))}</mark>`;
    pos = e;
  }
  return out + esc(t.slice(pos));
}
const dlBtn = (id, kind, label, enabled = true, primary = false) =>
  `<button class="btn sm ${primary ? "primary" : ""}" data-dl="${esc(kind)}" data-id="${esc(id)}" ${enabled ? "" : "disabled"}>${ICON.down}${esc(label)}</button>`;
async function download(btn) {
  const id = btn.dataset.id, kind = btn.dataset.dl, label = btn.innerHTML;
  btn.classList.add("busy");
  btn.innerHTML = `<span class="spin"></span>${kind === "redacted" ? "Redacting & verifying…" : "Preparing…"}`;
  try {
    const r = await fetch(`/api/docs/${id}/download/${kind}`);
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || "Download failed"); }
    const m = (r.headers.get("content-disposition") || "").match(/filename="([^"]+)"/);
    const url = URL.createObjectURL(await r.blob()), a = document.createElement("a");
    a.href = url; a.download = m ? m[1] : kind; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
    toast(kind === "redacted" ? "Redacted file verified by re-scan and saved" : "Saved", "ok");
  } catch (e) { toast(e.message, "err"); }
  btn.classList.remove("busy"); btn.innerHTML = label;
}
async function approveDoc(id, input) {
  const name = input.value.trim();
  if (!name) { input.focus(); toast("Enter the reviewer's name to approve", "warn"); return; }
  try {
    upsert(await api(`/api/docs/${id}/approve`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }) }));
    toast(`Approved by ${name}. Output released.`, "ok");
    render();
  } catch (e) { toast(e.message, "err"); }
}
async function removeDoc(id, row) {
  try { await api(`/api/docs/${id}`, { method: "DELETE" }); } catch (e) { toast(e.message, "err"); return; }
  if (row) { row.classList.add("leaving"); await new Promise((r) => setTimeout(r, 260)); }
  S.docs = S.docs.filter((d) => d.id !== id);
  delete S.detail[id]; delete S.blocks[id]; delete S.rblocks[id];
  if (S.cur === id) S.cur = S.docs[0] ? S.docs[0].id : null;
  if (S.view !== "scan" && !S.cur) location.hash = "#/scan"; else render();
}
const hrow = (d) => `<div class="hrow ${d.id === S.cur ? "on" : ""}" data-pick="${esc(d.id)}">${fileIcon(d.type)}
  <div style="min-width:0"><div class="nm">${esc(d.name)}</div><div class="mt">${fmtN(d.counts.findings)} findings · ${clock(d.created)}</div></div>
  <span class="status ${d.status}">${d.status}</span><button class="x" data-del="${esc(d.id)}" data-tip="Remove from history">${ICON.x}</button></div>`;

/* doc picker in the top bar */
function docpick() {
  const d = S.cur ? summary(S.cur) : null, el = $("#docpick");
  el.innerHTML = S.docs.length ? `<button id="dp">${d ? fileIcon(d.type) : ""}<span class="n">${esc(d ? d.name : "Choose a document")}</span>${ICON.down2}</button>
    <div class="menu glass">${S.docs.map(hrow).join("")}</div>` : "";
}

/* global events */
document.addEventListener("mouseover", (e) => {
  const el = e.target.closest("[data-tip]"), tip = $("#tip");
  if (!el) { tip.classList.remove("on"); return; }
  tip.innerHTML = el.dataset.tip.split("\n").map(esc).join("<br>");
  tip.classList.add("on");
});
document.addEventListener("mousemove", (e) => {
  const tip = $("#tip");
  if (!tip.classList.contains("on")) return;
  tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 10) + "px";
  tip.style.top = Math.min(e.clientY + 16, innerHeight - tip.offsetHeight - 10) + "px";
});
document.addEventListener("click", (e) => {
  const del = e.target.closest("[data-del]");
  if (del) { e.stopPropagation(); e.preventDefault(); removeDoc(del.dataset.del, del.closest(".hrow")); return; }
  const pick = e.target.closest("[data-pick]");
  if (pick) { $("#docpick").classList.remove("open"); location.hash = `#/${S.view}/${pick.dataset.pick}`; return; }
  if (e.target.closest("#dp")) { $("#docpick").classList.toggle("open"); return; }
  if (!e.target.closest("#docpick")) $("#docpick").classList.remove("open");
  const dl = e.target.closest("[data-dl]");
  if (dl) { download(dl); return; }
  const ap = e.target.closest("[data-approve]");
  if (ap) { approveDoc(ap.dataset.approve, $(`#${ap.dataset.input}`)); return; }
  const go = e.target.closest("[data-go]");
  if (go) location.hash = go.dataset.go;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches("input[data-approve-input]")) approveDoc(e.target.dataset.approveInput, e.target);
  if (e.key === "Escape") $("#docpick").classList.remove("open");
});
window.addEventListener("resize", () => { segs(); tabs(); });

/* ------------------------------------------------------------------------------------------------ router */
function route() {
  const [, v = "scan", id = "", extra = ""] = (location.hash || "#/scan").split("/");
  S.view = ["scan", "review", "audit"].includes(v) ? v : "scan";
  if (id && summary(id)) S.cur = id;
  S.focus = extra ? decodeURIComponent(extra) : null;
  render();
}
window.addEventListener("hashchange", route);

let renderSeq = 0;
async function render() {
  const seq = ++renderSeq, d = S.cur ? summary(S.cur) : null;
  tabs(); docpick();
  const scroll = $("#scroll"), view = $("#view");
  scroll.classList.toggle("fill", S.view === "review" && !!d);
  if (S.view !== "scan" && !d) { view.innerHTML = emptyState("No document selected", "Scan a document first, then review and audit it here."); return; }
  try {
    const html = await { scan: vScan, review: vReview, audit: vAudit }[S.view](d);
    if (seq !== renderSeq) return;
    view.innerHTML = html;
    if (S.view !== "review") scroll.scrollTop = 0;
    animate(view);
    (MOUNT[S.view] || (() => {}))(d);
  } catch (e) {
    if (seq === renderSeq) view.innerHTML = emptyState("Something went wrong", e.message, false);
  }
}
const MOUNT = {};

/* ------------------------------------------------------------------------------------------------ scan */
function qHTML() {
  return S.queue.map((q) => `<div class="qitem glass" id="q-${q.key}">${fileIcon(q.ext)}
    <div style="min-width:0"><div class="nm">${esc(q.name)}</div><div class="meta" id="qm-${q.key}">${qmeta(q)}</div>
      <div class="bar ${q.status === "done" ? "done" : q.status === "fail" ? "fail" : ""}"><i></i></div></div>
    <div>${q.status === "done" ? `<span class="status ${q.doc.status}">${q.doc.status}</span>` : q.status === "fail" ? `<span class="status BLOCKED">ERROR</span>` : ""}</div></div>`).join("");
}
function qmeta(q) {
  const el = ((q.t1 || performance.now()) - (q.t0 || performance.now())) / 1000;
  if (q.status === "queued") return `${bytes(q.size)} · waiting`;
  if (q.status === "scanning") return `Reading, detecting and verifying · ${el.toFixed(1)}s`;
  if (q.status === "done") return `${fmtN(q.doc.counts.findings)} findings in ${q.doc.elapsed}s`;
  return esc(q.err);
}
async function vScan(d) {
  return `<div class="view stagger">
    <div class="grid g-hero">
      <label class="drop glass" id="drop"><span class="ring-d"></span><input type="file" id="file" multiple accept=".pdf,.pptx,.docx">
        <div class="ico">${ICON.upload}</div><h2>Drop documents to scan</h2><p>PDF (including scans), PPTX and DOCX, up to 100 MB</p>
        <div class="opts"><label class="switch" id="deepsw"><input type="checkbox" id="deep" ${S.deep ? "checked" : ""}><span class="track"></span>Deep name model (slower)</label></div>
      </label>
      <div class="hist glass"><div class="hd"><h3>History</h3><span class="sub">${S.docs.length || ""}</span></div>
        <div class="list">${S.docs.length ? S.docs.map(hrow).join("") : `<div class="none">Scanned files appear here.</div>`}</div></div>
    </div>
    <div class="queue" id="queue">${qHTML()}</div>
    <div id="dash">${d ? dashboard(d) : ""}</div>
  </div>`;
}
MOUNT.scan = () => {
  const drop = $("#drop"), inp = $("#file");
  $("#deepsw").addEventListener("click", (e) => e.stopPropagation());
  $("#deep").addEventListener("change", (e) => { S.deep = e.target.checked; });
  inp.addEventListener("change", () => { enqueue(inp.files); inp.value = ""; });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => enqueue(e.dataTransfer.files));
};
function enqueue(files) {
  const all = Array.from(files || []), ok = all.filter((f) => /\.(pdf|pptx|docx)$/i.test(f.name));
  if (ok.length < all.length) toast("Only PDF, PPTX and DOCX files are supported", "warn");
  for (const f of ok) S.queue.push({ key: Math.random().toString(36).slice(2, 9), file: f, name: f.name, size: f.size, ext: f.name.split(".").pop(), status: "queued" });
  refreshQueue(); pump();
}
function refreshQueue() { const q = $("#queue"); if (q) q.innerHTML = qHTML(); }
async function pump() {
  if (S.busy) return;
  const q = S.queue.find((x) => x.status === "queued");
  if (!q) return;
  S.busy = true; q.status = "scanning"; q.t0 = performance.now();
  refreshQueue();
  const tick = setInterval(() => { const m = $(`#qm-${q.key}`); if (m) m.innerHTML = qmeta(q); }, 100);
  try {
    const fd = new FormData();
    fd.append("file", q.file); fd.append("deep", S.deep ? "1" : "0");
    const doc = await api("/api/scan", { method: "POST", body: fd });
    q.t1 = performance.now(); q.status = "done"; q.doc = doc; delete q.file;
    upsert(doc); S.cur = doc.id;
  } catch (e) { q.t1 = performance.now(); q.status = "fail"; q.err = e.message; toast(`${q.name}: ${e.message}`, "err"); }
  clearInterval(tick);
  S.busy = false;
  setTimeout(() => { S.queue = S.queue.filter((x) => x !== q || x.status === "fail"); refreshQueue(); }, 2200);
  if (S.view === "scan" && q.status === "done") { history.replaceState(null, "", `#/scan/${S.cur}`); render(); }
  else { refreshQueue(); tabs(); docpick(); }
  pump();
}

function dashboard(d) {
  const a = d.accuracy, q = d.quality, by = d.counts.by_type, dis = d.counts.distinct_by_type || {};
  const maxT = Math.max(1, ...Object.values(by)), groups = d.groups || [], maxG = Math.max(1, ...groups.map((g) => g.hits));
  const cf = d.confidentiality || {}, cl = CONF[cf.label] || ["#5f6e82", 0];
  const unit = d.units.label === "Sections" ? "section" : d.units.label.slice(0, -1).toLowerCase();
  const pt = a ? Object.entries(a.per_type) : [];
  return `<div class="stagger">
  <div class="section-title"><h2>Results</h2></div>
  <div class="dochead glass">${fileIcon(d.type, true)}
    <div class="t"><b>${esc(d.name)}</b><span>${bytes(d.size)} · scanned at ${clock(d.created)}${d.deep ? " · deep model" : ""}</span></div>
    <div class="stats"><div><b>${cnt(d.counts.findings)}</b><span>Findings</span></div><div><b>${cnt(d.counts.distinct)}</b><span>Distinct</span></div>
      <div><b>${cnt(d.units.count)}</b><span>${esc(d.units.label)}</span></div><div><b>${cnt(d.elapsed, 1)}<small>s</small></b><span>Scan time</span></div></div>
    <div class="acts"><button class="btn primary" data-go="#/review/${d.id}">${ICON.eye}Review</button><button class="btn" data-go="#/audit/${d.id}">Audit</button></div>
  </div>

  <div class="grid g3 mt">
    <div class="card glass decision"><h3>Release decision</h3>
      <div style="margin-top:14px"><span class="status big ${d.status}">${d.status}</span></div>
      <p>${STATUS_TEXT[d.status]}</p>
      ${d.reasons.length ? `<ul class="reasons">${d.reasons.slice(0, 3).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : ""}
      ${d.needs_approval ? `<div class="approve"><input class="input" id="ap-dash" placeholder="Reviewer name" data-approve-input="${d.id}"><button class="btn primary" data-approve="${d.id}" data-input="ap-dash">Approve</button></div>` : ""}
      ${d.released ? `<div class="note ok">Released${d.approved_by ? ` · approved by ${esc(d.approved_by)}` : ""}</div><div class="row mt" style="flex-wrap:wrap">${dlBtn(d.id, "sanitized.txt", "Sanitised text", true, true)}${dlBtn(d.id, "redacted", "Redacted file")}</div>` : ""}
    </div>

    <div class="card glass">${a ? `<h3>Accuracy · against ground truth</h3>
      <div class="rings">${ring(a.recall, "Recall", "#0a84ff", a.recall_ci95 ? `95% CI ${pct(a.recall_ci95[0], 0)}–${pct(a.recall_ci95[1], 0)}` : "")}${ring(a.precision, "Precision", "#5e5ce6")}${ring(a.f1, "F1", "#30b0c7")}</div>
      <div class="pill-line ${a.leaked ? "bad" : "ok"}">${a.leaked ? ICON.warn : ICON.ok}<b>${a.leaked}/${a.gt_values}</b>${a.leaked ? "values still readable after sanitising" : "values leaked after sanitising"}</div>
      ${pt.length > 1 ? `<div class="pertype"><span class="h">Type</span><span></span><span class="h">Recall</span><span class="h">Prec.</span>
        ${pt.map(([t, v]) => `${tpill(t)}<span class="trk"><i data-w="${(v.recall || 0) * 100}%"></i></span><span class="v">${pct(v.recall, 0)}</span><span class="v">${pct(v.precision, 0)}</span>`).join("")}</div>` : ""}`
      : `<h3>Confidence · no ground truth for this file</h3>
      <div class="rings">${ring(q.mean_confidence, "Mean confidence", "#0a84ff")}${ring(q.high_confidence_share, "High confidence", "#5e5ce6", "share ≥ 0.80")}${ring(q.mean_ocr_confidence != null ? q.mean_ocr_confidence / 100 : null, "OCR quality", "#30b0c7")}</div>
      <div class="pill-line ${q.verifier_hard ? "bad" : "ok"}">${q.verifier_hard ? ICON.warn : ICON.ok}<b>${q.verifier_hard}</b>residual hits from the independent verifier</div>
      <div class="gtnote">Accuracy is reported only where it was measured. These are confidence signals, not accuracy.</div>`}
    </div>

    <div class="card glass"><h3>Confidentiality</h3>
      <div class="conf-label" style="color:${cl[0]}">${esc(cf.label || "—")}</div>
      <div class="sub">Exposure score ${cf.score ?? "—"}</div>
      <div class="conf-scale l${cl[1]}"><i></i><i></i><i></i><i></i></div>
      <div class="conf-names"><span>Public</span><span>Internal</span><span>Confid.</span><span>Restricted</span></div>
      <ul class="why">${(cf.reasons || []).slice(0, 4).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
    </div>
  </div>

  <div class="grid g2 mt">
    <div class="card glass"><h3>Findings by type</h3>
      <div class="hbars">${Object.entries(by).map(([t, n]) => { const i = tinfo(t); return `<div class="hbar">${tpill(t)}
        <div class="trk"><i data-w="${(n / maxT) * 100}%" style="background:linear-gradient(90deg, ${i.bg}, ${i.c})"></i></div>
        <span class="n">${fmtN(n)} <small>· ${fmtN(dis[t] || 0)} unique</small></span></div>`; }).join("") || `<div class="sub">No personal data found.</div>`}</div>
    </div>
    <div class="card glass"><div class="row between"><h3>Hits per ${esc(unit)}</h3><span class="sub">Hover for details · click to open</span></div>
      ${hitsChart(d, groups, unit)}
    </div>
  </div>
  </div>`;
}

function niceMax(m) { const p = Math.pow(10, Math.floor(Math.log10(Math.max(1, m)))); for (const k of [1, 2, 2.5, 5, 10]) if (k * p >= m) return k * p; return 10 * p; }
function hitsChart(d, groups, unit) {
  if (!groups.length) return `<div class="sub mt">Nothing extracted.</div>`;
  const top = niceMax(Math.max(1, ...groups.map((g) => g.hits))), every = groups.length > 24 ? 5 : groups.length > 12 ? 2 : 1;
  const xl = (g, i) => (g.index != null ? g.index : i + 1);
  return `<div class="chart"><div class="yt">Hits</div>
    <div class="yax">${[0, 0.5, 1].map((f) => `<span style="bottom:${f * 100}%">${Math.round(top * f)}</span>`).join("")}</div>
    <div class="plot"><i class="gl" style="bottom:50%"></i><i class="gl" style="bottom:100%"></i>
      ${groups.map((g, i) => `<div class="col ${g.hits ? "" : "zero"}" data-go="#/review/${d.id}/${encodeURIComponent(g.label)}"
        data-tip="${esc(g.label)}\n${g.hits} hit(s)${Object.keys(g.by_type).length ? "\n" + Object.entries(g.by_type).map(([t, n]) => `${tinfo(t).n}: ${n}`).join(", ") : ""}">
        <div class="b" data-h="${g.hits ? Math.max(2, (g.hits / top) * 100) : 1}%"></div></div>`).join("")}</div>
    <div class="xax">${groups.map((g, i) => `<span>${(i % every === 0 || i === groups.length - 1) ? xl(g, i) : ""}</span>`).join("")}</div>
    <div class="xt">${esc(unit.charAt(0).toUpperCase() + unit.slice(1))}${groups.some((g) => g.index == null) ? "s in reading order" : " number"}</div></div>`;
}

/* ------------------------------------------------------------------------------------------------ review */
async function vReview(d) {
  const [det, bl] = await Promise.all([detail(d.id), blocks(d.id)]);
  if (S.review.doc !== d.id) S.review = { ...S.review, doc: d.id, mode: d.has_pages ? "pages" : "text" };
  const mode = d.has_pages ? S.review.mode : "text", npages = d.has_pages ? d.stats.page_count || 0 : 0, W = Math.round(860 * S.review.zoom);
  const byGroup = {};
  for (const f of det.findings) (byGroup[f.where] = byGroup[f.where] || []).push(f);
  const order = d.groups.map((g) => g.label).filter((l) => byGroup[l]);
  const TAG = { hard: "RESIDUAL", soft: "VERIFIER", cand: "UNSURE", miss: "MISSED" };
  const attn = det.attention || [];
  S.review.attn = attn;
  const tab = S.review.tab, grouped = {};
  for (const b of bl) (grouped[b.group] = grouped[b.group] || []).push(b);
  const body = mode === "pages"
    ? Array.from({ length: npages }, (_, i) => { const g = d.groups.find((x) => x.index === i + 1) || { hits: 0 };
        return `<figure class="page" id="pg-${i + 1}" data-n="${i + 1}" style="max-width:${W}px"><div class="ph"></div>
          <figcaption><span>Page ${i + 1}</span>${g.hits ? `<span class="h">${g.hits} hit${g.hits > 1 ? "s" : ""}</span>` : ""}</figcaption></figure>`; }).join("")
    : Object.entries(grouped).map(([g, bs]) => { const hits = bs.reduce((s, b) => s + b.hits, 0);
        return `<section class="paper" id="grp-${esc(slug(g))}" style="max-width:${W}px"><h4>${esc(g)}${hits ? ` <span class="n">· ${hits} hit${hits > 1 ? "s" : ""}</span>` : ""}</h4>
          ${bs.map((b) => `<div class="blk ${b.hidden ? "hidden" : ""}" id="blk-${esc(b.id)}" data-id="${esc(b.id)}">${b.source === "ocr" ? `<span class="src">OCR${b.ocr_conf != null ? " " + Math.round(b.ocr_conf) + "%" : ""}</span>` : ""}${b.part && !b.part.startsWith("image:") ? `<span class="part">${esc(b.part)}</span>` : ""}<span class="tx">${blockHTML(b)}</span></div>`).join("")}</section>`; }).join("");
  return `<div class="view review">
    <div class="viewer glass">
      <div class="vbar">
        ${d.has_pages ? `<div class="seg" id="mode"><span class="thumb"></span><button data-m="pages" class="${mode === "pages" ? "on" : ""}">Pages</button><button data-m="text" class="${mode === "text" ? "on" : ""}">Text</button></div>` : ""}
        <span class="pg" id="pgind">${mode === "pages" ? `Page 1 of ${npages}` : `${Object.keys(grouped).length} sections`}</span>
        <span class="grow"></span>
        ${mode === "text" && d.status !== "BLOCKED" ? `<span class="sub" style="font-size:12px">Select text to redact it</span>` : ""}
        <button class="btn sm peek" id="peek" data-tip="Press and hold to see the original values">${ICON.eye}Hold to peek</button>
        <button class="btn sm icon" id="zout" data-tip="Zoom out">−</button><button class="btn sm icon" id="zin" data-tip="Zoom in">+</button>
      </div>
      <div class="pages" id="pages">${body || `<div class="empty"><p>No extracted text.</p></div>`}</div>
    </div>
    <aside class="panel glass">
      <div class="phead">
        <div class="row between"><span class="status ${d.status}">${d.status}</span><span class="sub">${fmtN(det.findings.length)} hits · ${order.length} places</span></div>
        <div class="seg mt" id="rtab" style="display:flex"><span class="thumb"></span><button data-t="hits" class="${tab === "hits" ? "on" : ""}" style="flex:1">Hits</button><button data-t="attn" class="${tab === "attn" ? "on" : ""}" style="flex:1">Needs attention · ${attn.length}</button></div>
      </div>
      <div class="panel-scroll">
        ${tab === "hits" ? order.map((g, gi) => `<div class="grp ${gi === 0 || S.focus === g ? "open" : ""}"><button>${ICON.chev}${esc(g)}<span class="c">${byGroup[g].length}</span></button>
          <div class="items"><div>${byGroup[g].map((f) => `<div class="hit" data-f="${esc(f.id)}" data-tip="${esc(f.detectors.join(", "))}">${tpill(f.type)}<span class="tk">${esc(f.token)}</span><span class="cf">${f.confidence.toFixed(2)}</span></div>`).join("")}</div></div></div>`).join("") || `<div class="note">No personal data found.</div>`
        : attn.map((x) => `<div class="attn ${x.kind}" data-k="${esc(x.key)}">
            <div class="ah"><b>${TAG[x.kind]}</b>${x.type ? tpill(x.type) : ""}<span>${esc(x.where)}${x.box && x.page ? "" : ""}</span></div>
            ${x.snippet ? `<div class="snip">${esc(x.snippet[0])}<mark>${esc(x.snippet[1])}</mark>${esc(x.snippet[2])}</div>` : ""}
            <div class="why">${esc(x.why)}</div>
            ${d.status !== "BLOCKED" ? `<div class="aa"><select class="input tsel">${Object.keys(TYPE).map((t) => `<option value="${t}" ${t === (x.type || "PERSON") ? "selected" : ""}>${esc(tinfo(t).n)}</option>`).join("")}</select>
              <button class="btn sm primary" data-redact="${esc(x.key)}">Redact</button><button class="btn sm" data-dismiss="${esc(x.key)}">Dismiss</button></div>` : ""}
          </div>`).join("") || `<div class="pill-line ok">${ICON.ok}Nothing needs attention.</div>`}
      </div>
      <div class="pfoot">
        ${d.needs_approval ? `<div class="approve" style="margin:0"><input class="input" id="ap-rev" placeholder="Reviewer name" data-approve-input="${d.id}"><button class="btn primary" data-approve="${d.id}" data-input="ap-rev">Approve</button></div>`
        : d.released ? `<div class="row" style="flex-wrap:wrap">${dlBtn(d.id, "sanitized.txt", "Sanitised text", true, true)}${dlBtn(d.id, "redacted", "Redacted file")}</div>`
        : `<div class="note" style="margin:0;color:var(--red)">Blocked. Nothing can be released from this document.</div>`}
      </div>
    </aside>
  </div>`;
}
MOUNT.review = (d) => {
  const pages = $("#pages");
  let peeking = false;
  $("#mode")?.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { S.review.mode = b.dataset.m; render(); } });
  $("#rtab").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { S.review.tab = b.dataset.t; render(); } });
  const zoom = (k) => { S.review.zoom = Math.max(0.6, Math.min(1.8, S.review.zoom * k)); $$(".page, .paper", pages).forEach((p) => { p.style.maxWidth = Math.round(860 * S.review.zoom) + "px"; }); };
  $("#zin").onclick = () => zoom(1.15); $("#zout").onclick = () => zoom(1 / 1.15);
  $$(".grp > button").forEach((b) => b.addEventListener("click", () => b.parentElement.classList.toggle("open")));
  const pageSrc = (n, rv) => `/api/docs/${d.id}/page/${n}?reveal=${rv ? 1 : 0}&v=${d.rev || 0}`;
  const swapImg = (img, src) => { const pre = new Image(); pre.onload = () => { img.src = src; }; pre.src = src; };

  /* hold-to-peek: originals are on screen only while the button is held */
  const peek = async (on) => {
    if (peeking === on) return;
    peeking = on; $("#peek")?.classList.toggle("on", on);
    if (S.review.mode === "pages" && d.has_pages) { $$(".page img", pages).forEach((img) => swapImg(img, pageSrc(img.closest(".page").dataset.n, on))); return; }
    if (on && !S.rblocks[d.id]) S.rblocks[d.id] = await api(`/api/docs/${d.id}/blocks?reveal=1`);
    if (peeking !== on) return;
    const src = Object.fromEntries((on ? S.rblocks[d.id] : S.blocks[d.id]).map((b) => [b.id, b]));
    $$(".blk[data-id]", pages).forEach((el) => { const b = src[el.dataset.id]; if (b) $(".tx", el).innerHTML = blockHTML(b, on); });
  };
  const pk = $("#peek");
  pk.addEventListener("pointerdown", (e) => { e.preventDefault(); peek(true); });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => pk.addEventListener(ev, () => peek(false)));
  window.addEventListener("blur", () => peek(false), { once: true });

  if (S.review.mode === "pages" && d.has_pages) {
    const io = new IntersectionObserver((ents) => ents.forEach((en) => {
      if (!en.isIntersecting) return;
      const fig = en.target; io.unobserve(fig);
      const img = new Image(); img.alt = `Page ${fig.dataset.n}`; img.decoding = "async";
      img.onload = () => { fig.querySelector(".ph")?.remove(); if (!img.isConnected) fig.prepend(img); requestAnimationFrame(() => img.classList.add("ld")); };
      img.src = pageSrc(fig.dataset.n, peeking);
    }), { root: pages, rootMargin: "900px 0px" });
    $$(".page", pages).forEach((f) => io.observe(f));
    const ind = $("#pgind"), figs = $$(".page", pages);
    pages.addEventListener("scroll", () => {
      const mid = pages.scrollTop + pages.clientHeight / 3;
      let cur = 1; for (const f of figs) { if (f.offsetTop <= mid) cur = +f.dataset.n; else break; }
      ind.textContent = `Page ${cur} of ${figs.length}`;
    }, { passive: true });
  }
  const attnByKey = Object.fromEntries((S.review.attn || []).map((x) => [x.key, x]));
  const placeMarks = (fig) => {
    for (const x of S.review.attn || []) if (x.box && String(x.page) === fig.dataset.n && !fig.querySelector(`[data-mk="${CSS.escape(x.key)}"]`)) {
      const m = document.createElement("div"); m.className = `amark ${x.kind}`; m.dataset.mk = x.key;
      const [x0, y0, x1, y1] = x.box; Object.assign(m.style, { left: x0 * 100 + "%", top: y0 * 100 + "%", width: (x1 - x0) * 100 + "%", height: (y1 - y0) * 100 + "%" });
      fig.appendChild(m);
    }
  };
  $$(".page", pages).forEach(placeMarks);
  const focusAttn = (x) => {
    if (S.review.mode === "pages" && d.has_pages) {
      const fig = x.page && $(`#pg-${x.page}`);
      if (fig) { flash(fig); const mk = fig.querySelector(`[data-mk="${CSS.escape(x.key)}"]`); if (mk) { mk.scrollIntoView({ behavior: "smooth", block: "center" }); mk.classList.remove("pulse"); void mk.offsetWidth; mk.classList.add("pulse"); } return; }
      S.review.mode = "text"; S.focus = "attn:" + x.key; return render();
    }
    const el = $(`#blk-${CSS.escape(x.block_id)}`);
    if (!el) return;
    if (x.s) { const b = (S.blocks[d.id] || []).find((y) => y.id === x.block_id); if (b && !b.hidden) $(".tx", el).innerHTML = tokenHTML(b.text.slice(0, x.s[0])) + `<mark class="focus">${tokenHTML(b.text.slice(x.s[0], x.s[1]))}</mark>` + tokenHTML(b.text.slice(x.s[1])); }
    flash(el);
  };
  const afterEdit = async (doc, msg) => {
    S.review.keep = pages.scrollTop;
    upsert(doc); delete S.blocks[d.id]; delete S.rblocks[d.id];
    toast(msg, "ok"); render();
  };
  $(".panel-scroll").addEventListener("click", async (e) => {
    const rb = e.target.closest("[data-redact]"), db = e.target.closest("[data-dismiss]");
    if (rb) {
      const x = attnByKey[rb.dataset.redact], typ = rb.parentElement.querySelector(".tsel").value;
      const body = x.o ? { block_id: x.block_id, start: x.o[0], end: x.o[1], coords: "original", type: typ } : { block_id: x.block_id, start: x.s[0], end: x.s[1], coords: "sanitized", type: typ };
      rb.classList.add("busy");
      try { const doc = await api(`/api/docs/${d.id}/redact`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }); afterEdit(doc, `Redacted ${doc.added} occurrence(s). Approve to release.`); }
      catch (err) { rb.classList.remove("busy"); toast(err.message, "err"); }
      return;
    }
    if (db) {
      const card = db.closest(".attn");
      try { await api(`/api/docs/${d.id}/dismiss`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key: db.dataset.dismiss }) }); } catch (err) { toast(err.message, "err"); return; }
      delete S.detail[d.id]; card.style.transition = "opacity .3s, transform .3s"; card.style.opacity = 0; card.style.transform = "translateX(16px)";
      $(`[data-mk="${CSS.escape(db.dataset.dismiss)}"]`)?.remove(); setTimeout(() => card.remove(), 300);
      return;
    }
    if (e.target.closest("select")) return;
    const ak = e.target.closest("[data-k]");
    if (ak && attnByKey[ak.dataset.k]) focusAttn(attnByKey[ak.dataset.k]);
  });
  /* select text (text view) -> redact */
  let bar = null;
  const hideBar = () => { bar?.remove(); bar = null; };
  if (d.status !== "BLOCKED") pages.addEventListener("mouseup", () => setTimeout(() => {
    const sel = getSelection();
    hideBar();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    const r = sel.getRangeAt(0), tx = r.startContainer.parentElement?.closest(".tx");
    if (!tx || tx !== r.endContainer.parentElement?.closest(".tx") || r.toString().trim().length < 2) return;
    const pre = document.createRange(); pre.selectNodeContents(tx); pre.setEnd(r.startContainer, r.startOffset);
    const start = pre.toString().length, end = start + r.toString().length, bid = tx.closest(".blk").dataset.id, rect = r.getBoundingClientRect();
    bar = document.createElement("div"); bar.className = "selbar glass";
    bar.innerHTML = `<select class="input tsel">${Object.keys(TYPE).map((t) => `<option value="${t}">${esc(tinfo(t).n)}</option>`).join("")}</select><button class="btn sm primary">Redact selection</button>`;
    bar.style.left = Math.max(12, Math.min(innerWidth - 300, rect.left)) + "px"; bar.style.top = Math.max(80, rect.top - 52) + "px";
    document.body.appendChild(bar);
    bar.querySelector("button").onclick = async () => {
      try { const doc = await api(`/api/docs/${d.id}/redact`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ block_id: bid, start, end, coords: "sanitized", type: bar.querySelector("select").value }) }); hideBar(); afterEdit(doc, `Redacted ${doc.added} occurrence(s). Approve to release.`); }
      catch (err) { toast(err.message, "err"); }
    };
  }, 0));
  pages.addEventListener("scroll", hideBar, { passive: true });
  window.addEventListener("hashchange", hideBar, { once: true });
  if (S.review.keep != null) { pages.style.scrollBehavior = "auto"; pages.scrollTop = S.review.keep; pages.style.scrollBehavior = ""; S.review.keep = null; }
  const byId = Object.fromEntries((S.detail[d.id]?.findings || []).map((f) => [f.id, f]));
  const blockInfo = Object.fromEntries((S.blocks[d.id] || []).map((b) => [b.id, b]));
  const focusBlock = (bid) => {
    const b = blockInfo[bid];
    if (S.review.mode === "pages" && d.has_pages) {
      if (b && b.index) return flash($(`#pg-${b.index}`));
      S.review.mode = "text"; S.focus = "block:" + bid; return render();
    }
    flash($(`#blk-${CSS.escape(bid)}`));
  };
  $(".panel-scroll").addEventListener("click", (e) => {
    const h = e.target.closest("[data-f]");
    if (h && byId[h.dataset.f]) focusBlock(byId[h.dataset.f].block_id);
  });
  if (S.focus) {
    const f = S.focus; S.focus = null;
    setTimeout(() => {
      if (f.startsWith("block:")) return focusBlock(f.slice(6));
      if (f.startsWith("attn:")) { const x = attnByKey[f.slice(5)]; if (x) focusAttn(x); return; }
      const g = d.groups.find((x) => x.label === f);
      if (g && S.review.mode === "pages" && g.index) flash($(`#pg-${g.index}`)); else flash($(`#grp-${slug(f)}`));
    }, 120);
  }
};
function flash(el) {
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
}

/* ------------------------------------------------------------------------------------------------ audit */
const PER = 50;
async function vAudit(d) {
  const det = await detail(d.id), A = S.audit, v = det.verification, st = d.stats || {};
  if (A.doc !== d.id) Object.assign(A, { doc: d.id, q: "", types: new Set(), page: 0 });
  const hard = v.hits.filter((h) => h.severity === "HARD").length;
  let body = "";
  if (A.tab === "findings") {
    const all = det.findings, q = A.q.toLowerCase();
    const rows = all.filter((f) => (!A.types.size || A.types.has(f.type)) && (!q || [f.id, f.token, f.where, f.detectors.join(" ")].join(" ").toLowerCase().includes(q)));
    const [sk, sd] = A.sort;
    rows.sort((x, y) => { const a = x[sk], b = y[sk]; return (typeof a === "number" ? a - b : String(a).localeCompare(String(b), undefined, { numeric: true })) * sd; });
    const pages = Math.max(1, Math.ceil(rows.length / PER)); A.page = Math.min(A.page, pages - 1);
    const counts = {}; for (const f of all) counts[f.type] = (counts[f.type] || 0) + 1;
    const th = (k, l, num = false) => `<th class="sort ${num ? "num" : ""} ${sk === k ? "on" : ""}" data-s="${k}">${l}<span class="ar">${sk === k ? (sd > 0 ? "↑" : "↓") : "↕"}</span></th>`;
    body = `<div class="card glass">
      <div class="toolbar"><div class="search">${ICON.search}<input class="input" id="aq" placeholder="Search token, location, detector" value="${esc(A.q)}"></div><span class="grow"></span>
        <div class="chips" id="achips">${Object.entries(counts).sort((x, y) => y[1] - x[1]).map(([t, n]) => `<button class="chip ${A.types.has(t) ? "on" : ""}" data-t="${esc(t)}"><i style="background:${tinfo(t).c}"></i>${esc(tinfo(t).n)}<span class="n">${n}</span></button>`).join("")}</div></div>
      <div class="tbl-wrap"><table class="tbl" id="atbl"><thead><tr>${th("id", "ID")}${th("type", "Type")}${th("token", "Token")}${th("where", "Location")}${th("confidence", "Confidence", true)}<th>Detectors</th>${th("source", "Source")}<th>Fingerprint</th></tr></thead>
        <tbody>${rows.slice(A.page * PER, A.page * PER + PER).map((f) => `<tr class="click" data-go="#/review/${d.id}/${encodeURIComponent("block:" + f.block_id)}"><td class="mono muted">${esc(f.id)}</td><td>${tpill(f.type)}</td><td class="mono">${esc(f.token)}</td>
          <td>${esc(f.where)}${f.part && !f.part.startsWith("image:") ? `<div class="muted" style="font-size:11.5px">${esc(f.part)}</div>` : ""}</td>
          <td class="num"><span class="cbar"><span class="trk"><i style="width:${f.confidence * 100}%;background:${f.confidence >= 0.8 ? "#0a84ff" : f.confidence >= 0.6 ? "#5e5ce6" : "#ff9f0a"}"></i></span>${f.confidence.toFixed(2)}</span></td>
          <td>${f.detectors.slice(0, 2).map((x) => `<span class="det">${esc(x)}</span>`).join("")}${f.detectors.length > 2 ? `<span class="det" data-tip="${esc(f.detectors.slice(2).join("\n"))}">+${f.detectors.length - 2}</span>` : ""}</td>
          <td><span class="badge ${f.ocr ? "ocr" : "native"}">${f.ocr ? "OCR" : "TEXT"}</span></td><td class="mono muted">${esc(f.fingerprint)}</td></tr>`).join("") || `<tr><td colspan="8" class="muted" style="text-align:center;padding:30px">No findings match.</td></tr>`}</tbody></table></div>
      <div class="pager"><span>${fmtN(rows.length)} findings · page ${A.page + 1} of ${pages}</span><button class="btn sm" id="aprev" ${A.page ? "" : "disabled"}>Previous</button><button class="btn sm" id="anext" ${A.page < pages - 1 ? "" : "disabled"}>Next</button></div>
    </div>`;
  } else if (A.tab === "pages") {
    const gs = d.groups, max = Math.max(1, ...gs.map((g) => g.hits));
    body = `<div class="card glass"><div class="row between" style="margin-bottom:14px"><h3>Personal data by ${esc(d.units.label === "Sections" ? "section" : d.units.label.slice(0, -1).toLowerCase())}</h3><span class="sub">Darker means more · ! means something to check · click to open</span></div>
      <div class="tiles">${gs.map((g) => { const heat = g.hits ? 0.1 + 0.8 * (g.hits / max) : 0, tot = Math.max(1, g.hits);
        return `<div class="tile ${heat > 0.5 ? "hot" : ""}" style="--heat:${heat.toFixed(3)}" data-go="#/review/${d.id}/${encodeURIComponent(g.label)}"
          data-tip="${esc(g.label)}\n${Object.entries(g.by_type).map(([t, n]) => `${tinfo(t).n}: ${n}`).join("\n") || "No hits"}${g.ocr_conf != null ? `\nOCR confidence ${Math.round(g.ocr_conf)}%` : ""}">
          ${g.verifier || g.review ? `<span class="flag">!</span>` : ""}<div class="lb">${esc(g.label)}</div><div class="hv">${g.hits}<small>hit${g.hits === 1 ? "" : "s"}</small></div>
          <div class="mix">${Object.entries(g.by_type).map(([t, n]) => `<i style="width:${(n / tot) * 100}%;background:${tinfo(t).c}"></i>`).join("")}</div>
          <div class="ft"><span>${g.mean_conf != null ? "conf " + g.mean_conf.toFixed(2) : ""}</span><span>${g.ocr_conf != null ? "OCR " + Math.round(g.ocr_conf) + "%" : ""}</span></div></div>`; }).join("")}</div></div>`;
  } else {
    const warn = [...(d.warnings || []), ...(st.unsupported_media || [])];
    body = `<div class="card glass"><div class="kv">
        <div><span>Text blocks</span><b>${cnt(st.block_count)}</b></div><div><span>Characters (text layer)</span><b>${cnt(st.native_chars)}</b></div>
        <div><span>Characters (OCR)</span><b>${cnt(st.ocr_chars)}</b></div><div><span>Mean OCR confidence</span><b>${st.mean_ocr_confidence != null ? cnt(st.mean_ocr_confidence, 1) + "%" : "—"}</b></div></div>
      ${warn.length ? `<ul class="warnlist mt">${warn.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}</div>
      <div class="card glass mt" style="padding:8px"><div class="tbl-wrap" style="max-height:460px"><table class="tbl"><thead><tr><th>Location</th><th class="num">Blocks</th><th class="num">Characters</th><th class="num">OCR blocks</th><th class="num">OCR confidence</th><th class="num">Ink read</th><th class="num">Hits</th></tr></thead>
        <tbody>${d.groups.map((g) => `<tr class="click" data-go="#/review/${d.id}/${encodeURIComponent(g.label)}"><td><b>${esc(g.label)}</b></td><td class="num">${g.blocks}</td><td class="num">${fmtN(g.chars)}</td><td class="num">${g.ocr_blocks || "—"}</td>
          <td class="num">${g.ocr_conf != null ? Math.round(g.ocr_conf) + "%" : "—"}</td><td class="num">${g.ink != null ? pct(g.ink, 0) : "—"}</td><td class="num">${g.hits}</td></tr>`).join("")}</tbody></table></div></div>`;
  }
  return `<div class="view stagger">
    <div class="dochead glass">${fileIcon(d.type, true)}
      <div class="t"><b>${esc(d.name)}</b><span><span class="status ${d.status}" style="height:20px;font-size:10.5px;margin-right:8px">${d.status}</span>Verifier ${v.passed ? "passed" : `flagged ${hard} residual`} · ${v.rules_run.length} rules${d.approved_by ? ` · approved by ${esc(d.approved_by)}` : ""} · config ${esc((d.config_digest || "").slice(0, 10))}</span></div>
      <div class="acts" style="flex-wrap:wrap;justify-content:flex-end">${dlBtn(d.id, "audit.json", "JSON")}${dlBtn(d.id, "audit.html", "HTML report")}${dlBtn(d.id, "redacted", "Redacted file", d.released, true)}</div>
    </div>
    <div class="row" style="justify-content:center;margin:22px 0 18px"><div class="seg big" id="atab"><span class="thumb"></span>
      ${[["findings", "Findings"], ["pages", "Coverage"], ["extraction", "Extraction"]].map(([k, l]) => `<button data-k="${k}" class="${A.tab === k ? "on" : ""}">${l}</button>`).join("")}</div></div>
    ${body}
  </div>`;
}
MOUNT.audit = () => {
  const A = S.audit;
  $("#atab").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b && b.dataset.k !== A.tab) { A.tab = b.dataset.k; render(); } });
  const aq = $("#aq");
  if (aq) {
    let t = null;
    aq.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { A.q = aq.value; A.page = 0; render().then(() => { const n = $("#aq"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }); }, 220); });
    $("#achips").addEventListener("click", (e) => { const b = e.target.closest("[data-t]"); if (!b) return; const k = b.dataset.t; A.types.has(k) ? A.types.delete(k) : A.types.add(k); A.page = 0; render(); });
    $("#atbl thead").addEventListener("click", (e) => { const th = e.target.closest("[data-s]"); if (!th) return; const k = th.dataset.s; A.sort = [k, A.sort[0] === k ? -A.sort[1] : k === "confidence" ? -1 : 1]; render(); });
    $("#aprev").onclick = () => { A.page--; render(); };
    $("#anext").onclick = () => { A.page++; render(); };
  }
};

/* ------------------------------------------------------------------------------------------------ boot */
(async function boot() {
  try { S.docs = await api("/api/docs"); } catch { S.docs = []; }
  if (!S.cur && S.docs.length) S.cur = S.docs[0].id;
  route();
  requestAnimationFrame(tabs);
})();
