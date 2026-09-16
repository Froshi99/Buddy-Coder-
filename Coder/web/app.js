"use strict";

/* ================================================================ Grundlagen */

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const nf = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });
const timeFmt = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("de-DE", { weekday: "long" });
const dateFmt = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "short" });

const state = {
  config: null,
  hardware: null,
  ollama: null,
  session: null,
  sessions: [],
  loaded: [],
  plan: null,
  busy: false,
  ws: null,
  live: null,           // streamende Agenten-Nachricht
  tools: new Map(),     // Werkzeug-ID -> Schritt-Element
  approvalId: null,
  renderQueued: false,
  runAgent: null,       // per @name angesprochener Agent des laufenden Auftrags
  runLabeled: false,
  ext: null,            // Agents und Befehle für den aktuellen Workspace
  modelLoading: false,
};

const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* privat */ } },
};

const forcedTheme = new URLSearchParams(location.search).get("theme");
if (!forcedTheme) {
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    document.documentElement.dataset.theme = e.matches ? "dark" : "light";
  });
}

const svg = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
const ICONS = {
  read_file: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>'),
  list_dir: svg('<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2h7.5A2.5 2.5 0 0 1 21 9.5v8a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5Z"/>'),
  glob: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
  grep: svg('<path d="M4 6h16M4 12h9M4 18h6"/><circle cx="17.5" cy="16.5" r="3"/><path d="m22 21-2.3-2.3"/>'),
  edit_file: svg('<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>'),
  write_file: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5M12 11v6M9 14h6"/>'),
  run_command: svg('<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 9 3 3-3 3M13 15h4"/>'),
  todo_write: svg('<path d="m4 7 2 2 3-3M4 16l2 2 3-3M13 8h7M13 17h7"/>'),
  check: svg('<path d="m5 12.5 4.5 4.5L19 7.5"/>'),
  cross: svg('<path d="M6 6l12 12M18 6 6 18"/>'),
  chevron: svg('<path d="m9 6 6 6-6 6"/>'),
  trash: svg('<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>'),
  copy: svg('<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>'),
  alert: svg('<path d="M12 8v5M12 16.5h.01"/><path d="M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/>'),
  sparkle: svg('<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.5 2.5M15.2 15.2l2.5 2.5M6.3 17.7l2.5-2.5M15.2 8.8l2.5-2.5"/>'),
  arrow: svg('<path d="m9 6 6 6-6 6"/>'),
  web_search: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9s1.3-6.4 3.8-9Z"/>'),
  web_fetch: svg('<path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/>'),
  up: svg('<path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/>'),
  agent: svg('<circle cx="9" cy="8" r="3.2"/><path d="M3.5 19.5a5.5 5.5 0 0 1 11 0"/><circle cx="17.2" cy="9.3" r="2.4"/><path d="M16 14.3a4.3 4.3 0 0 1 4.9 4.2"/>'),
  command: svg('<rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="m14 7.5-4 9"/>'),
  note: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>'),
  graph: svg('<circle cx="6" cy="7" r="2.4"/><circle cx="18" cy="6" r="2.4"/><circle cx="12" cy="18" r="2.4"/><path d="m8.3 6.6 7.4-.6M7.1 9.1l3.8 6.8M16.9 8.2l-3.8 7.7"/>'),
  memory_write: svg('<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h4"/><path d="M14 3v5h5v2M17.5 13.5a1.6 1.6 0 0 1 2.3 2.3L15 20.6l-3 .8.8-3Z"/>'),
  pin: svg('<path d="M9 4h6l-1 5 3 3v2H7v-2l3-3ZM12 14v6"/>'),
  back: svg('<path d="m15 6-6 6 6 6"/>'),
  image: svg('<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="m21 16-5-5-8 9"/>'),
  controller: svg('<path d="M12 3 5 6v5.5c0 4.3 3 8.2 7 9.5 4-1.3 7-5.2 7-9.5V6Z"/><path d="m9 12 2 2 4-4"/>'),
  mode: svg('<path d="M12 3 5 6v5.5c0 4.3 3 8.2 7 9.5 4-1.3 7-5.2 7-9.5V6Z"/>'),
  redo: svg('<path d="M20 12a8 8 0 1 1-2.4-5.7M20 4v5h-5"/>'),
  research: svg('<path d="M4 19V5a1 1 0 0 1 1-1h9l4 4v3"/><path d="M8 9h5M8 13h3"/><circle cx="16.5" cy="16.5" r="3"/><path d="m21 21-2.4-2.4"/>'),
  gear: svg('<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  sidebar: svg('<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>'),
  chip: svg('<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>'),
  compact: svg('<path d="M4 12h16M8 5l4 4 4-4M8 19l4-4 4 4"/>'),
  chat: svg('<path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12Z"/>'),
  undo: svg('<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H12"/>'),
};
ICONS.memory_search = ICONS.graph;
ICONS.memory_read = ICONS.note;
ICONS.folder = ICONS.list_dir;
ICONS.view_image = ICONS.image;
ICONS.web_research = ICONS.research;
const TOOL_LABEL = {
  read_file: "Gelesen", list_dir: "Ordner", glob: "Dateien gesucht", grep: "Code durchsucht",
  edit_file: "Bearbeitet", write_file: "Geschrieben", run_command: "Befehl", todo_write: "Aufgaben",
  web_search: "Web durchsucht", web_fetch: "Seite gelesen", web_research: "Recherchiert", view_image: "Bild angesehen",
  memory_search: "Gedächtnis durchsucht", memory_read: "Notiz gelesen", memory_write: "Notiz gespeichert",
};
const TOOL_VERB = {
  read_file: "Liest", list_dir: "Öffnet Ordner", glob: "Sucht Dateien", grep: "Durchsucht Code nach",
  edit_file: "Bearbeitet", write_file: "Schreibt", run_command: "Führt aus:", todo_write: "Plant die Aufgaben",
  web_search: "Sucht im Web nach", web_fetch: "Lädt", web_research: "Recherchiert:", view_image: "Sieht sich an:",
  memory_search: "Durchsucht das Gedächtnis nach", memory_read: "Liest die Notiz", memory_write: "Speichert die Notiz",
};
const APPROVAL_TITLE = {
  edit_file: "Datei bearbeiten?", write_file: "Datei schreiben?", run_command: "Befehl ausführen?",
  web_fetch: "Webseite abrufen?", web_research: "Im Internet recherchieren?",
};
const agentName = (name) => (name === "kontrolle" ? "Kontrolle" : `@${name}`);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const gb = (bytes) => `${nf.format(bytes / 1024 ** 3)} GB`;
const kctx = (n) => (n >= 1024 ? `${Math.round(n / 1024)}K` : String(n));
const pct = (share) => `${Math.round((share || 0) * 100)} %`;
const basename = (p) => String(p || "").split(/[\\/]/).filter(Boolean).pop() || String(p || "");
// Pfade werden per direction:rtl vorn gekürzt – LRM-Zeichen halten „C:\“ und Endstriche dabei an ihrem Platz.
const ltr = (s) => `\u200e${s || ""}\u200e`;

function duration(seconds) {
  if (seconds < 60) return `${seconds} s`;
  const m = Math.floor(seconds / 60);
  return `${m}:${String(seconds % 60).padStart(2, "0")} min`;
}

function whenLabel(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diffDays = Math.floor((today - new Date(d).setHours(0, 0, 0, 0)) / 86400000);
  if (diffDays <= 0) return timeFmt.format(d);
  if (diffDays === 1) return "Gestern";
  if (diffDays < 7) return dayFmt.format(d);
  return dateFmt.format(d);
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

let toastTimer;
function toast(text, { error = false, ms = 3200 } = {}) {
  const el = $("#toast");
  el.classList.toggle("error", error);
  el.classList.remove("leaving");
  el.innerHTML = `${error ? ICONS.alert : ""}<span>${esc(text)}</span>`;
  el.hidden = false;
  el.style.animation = "none";
  void el.offsetWidth;
  el.style.animation = "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.classList.add("leaving"); // ausblenden statt verschwinden
    toastTimer = setTimeout(() => {
      el.hidden = true;
      el.classList.remove("leaving");
    }, 240);
  }, ms);
}

/* ================================================================ Markdown */

// [[Titel]], [[Titel#Abschnitt]] und [[Titel|Anzeige]]: Links auf Notizen im Gedächtnis
const WIKILINK_RX = /\[\[([^[\]|#\n]+)(#[^[\]|\n]*)?(?:\|([^[\]\n]*))?\]\]/g;
const wikilink = (_, target, _section, alias) => `<a class="wikilink" data-note="${target.trim()}">${(alias || target).trim()}</a>`;

function inline(text) {
  return esc(text)
    .split(/(`[^`\n]+`)/g)
    .map((part, i) => i % 2
      ? `<code>${part.slice(1, -1)}</code>`
      : part
        .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
        .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>")
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
        .replace(WIKILINK_RX, wikilink))
    .join("");
}

const RX = {
  fence: /^\s*```\s*([\w+#.-]*)\s*$/,
  heading: /^(#{1,4})\s+(.*)$/,
  list: /^\s*([-*+]|\d+[.)])\s+(.*)$/,
  quote: /^\s*>\s?(.*)$/,
  hr: /^\s*([-*_])(\s*\1){2,}\s*$/,
  table: /^\s*\|.*\|\s*$/,
  tableSep: /^\s*\|?\s*:?-{2,}/,
};
const isBlock = (l) => RX.fence.test(l) || RX.heading.test(l) || RX.list.test(l) || RX.quote.test(l) || RX.hr.test(l);

function codeBlock(code, lang) {
  return `<div class="code"><div class="code-head"><span>${esc(lang || "code")}</span>` +
    `<button type="button" data-copy>${ICONS.copy}<span>Kopieren</span></button></div>` +
    `<pre><code>${esc(code)}</code></pre></div>`;
}

function markdown(src) {
  src = String(src || "").replace(/<tool_call>[\s\S]*?(<\/tool_call>|$)/g, "");
  const lines = src.split("\n");
  let html = "";
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if ((m = line.match(RX.fence))) {
      const buf = [];
      i++;
      while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++]);
      i++;
      html += codeBlock(buf.join("\n"), m[1]);
    } else if ((m = line.match(RX.heading))) {
      const n = m[1].length;
      html += `<h${n}>${inline(m[2])}</h${n}>`;
      i++;
    } else if (RX.hr.test(line)) {
      html += "<hr>";
      i++;
    } else if (RX.quote.test(line)) {
      const buf = [];
      while (i < lines.length && (m = lines[i].match(RX.quote))) { buf.push(m[1]); i++; }
      html += `<blockquote>${markdown(buf.join("\n"))}</blockquote>`;
    } else if (RX.list.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const items = [];
      while (i < lines.length) {
        if ((m = lines[i].match(RX.list))) { items.push(m[2]); i++; }
        else if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) { items[items.length - 1] += " " + lines[i].trim(); i++; }
        else break;
      }
      const tag = ordered ? "ol" : "ul";
      html += `<${tag}>${items.map((it) => `<li>${inline(it)}</li>`).join("")}</${tag}>`;
    } else if (RX.table.test(line) && RX.tableSep.test(lines[i + 1] || "")) {
      const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const head = cells(line);
      i += 2;
      let body = "";
      while (i < lines.length && RX.table.test(lines[i])) {
        body += `<tr>${cells(lines[i]).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`;
        i++;
      }
      html += `<table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table>`;
    } else if (!line.trim()) {
      i++;
    } else {
      const buf = [lines[i++]];
      while (i < lines.length && lines[i].trim() && !isBlock(lines[i]) && !RX.table.test(lines[i])) buf.push(lines[i++]);
      html += `<p>${buf.map(inline).join("<br>")}</p>`;
    }
  }
  return html;
}

/* Unified Diff mit Zeilennummern */
function diffHtml(diff) {
  let oldN = 0;
  let newN = 0;
  const rows = [];
  for (const l of String(diff || "").split("\n")) {
    if (l.startsWith("+++") || l.startsWith("---")) continue;
    const hunk = l.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)/);
    if (hunk) {
      oldN = +hunk[1];
      newN = +hunk[2];
      if (rows.length || newN > 1) rows.push(`<div class="dl hunk">Ab Zeile ${Math.max(1, newN)}</div>`);
    } else if (l.startsWith("…")) {
      rows.push(`<div class="dl hunk">${esc(l)}</div>`);
    } else {
      let cls = "", sign = "", num;
      if (l.startsWith("+")) { cls = "add"; sign = "+"; num = newN++; }
      else if (l.startsWith("-")) { cls = "del"; sign = "−"; num = oldN++; }
      else { num = newN++; oldN++; }
      rows.push(`<div class="dl ${cls}"><span class="ln">${num}</span><span class="sg">${sign}</span><span class="cd">${esc(l.slice(1)) || " "}</span></div>`);
    }
  }
  return `<div class="diff">${rows.join("")}</div>`;
}

/* ================================================================ Scrollen & Dock */

const scroller = $("#scroll");
let stickToBottom = true;
scroller.addEventListener("scroll", () => {
  stickToBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160;
});
function scrollDown(force = false) {
  if (force || stickToBottom) {
    scroller.style.scrollBehavior = "auto";
    scroller.scrollTop = scroller.scrollHeight;
    scroller.style.scrollBehavior = "";
  }
}
new ResizeObserver(() => {
  document.documentElement.style.setProperty("--dock-h", `${$("#dock").offsetHeight}px`);
  scrollDown();
}).observe($("#dock"));

/* ================================================================ Verlauf */

const thread = $("#thread");

function updateEmpty() {
  $("#empty").hidden = thread.childElementCount > 0;
}

function addUser(text, images = []) {
  const el = document.createElement("div");
  el.className = "turn user";
  // @agent oder /befehl am Anfang hervorheben
  const lead = String(text).match(/^(\s*)([@/][\w:-]+)/);
  const html = (lead ? `${esc(lead[1])}<span class="mention">${esc(lead[2])}</span>${esc(text.slice(lead[0].length))}` : esc(text))
    .replace(WIKILINK_RX, wikilink);
  const pictures = images.length
    ? `<div class="user-images">${images.map((id) => `<button type="button" class="user-image" data-image="${esc(id)}" aria-label="Bild vergrößern"><img src="/api/images/${encodeURIComponent(id)}" alt="Angehängtes Bild" loading="lazy"></button>`).join("")}</div>`
    : "";
  el.innerHTML = `${pictures}<div class="bubble">${html}</div>`;
  thread.append(el);
  updateEmpty();
  return el;
}

function lastUserTurn() {
  const turns = $$(".turn.user", thread);
  return turns[turns.length - 1] || null;
}

function addVisionNote(el, vision) {
  if (!el || !vision?.model) return;
  const note = document.createElement("details");
  note.className = "turn-note";
  note.innerHTML = `<summary>Bild beschrieben von ${esc(vision.model)}</summary><div class="md">${markdown(vision.text || "")}</div>`;
  el.append(note);
}

function addRecallNote(el, titles) {
  if (!el || !titles?.length) return;
  const note = document.createElement("div");
  note.className = "turn-note";
  note.innerHTML = `Aus dem Gedächtnis: ${titles.map((t) => `<a class="wikilink" data-note="${esc(t)}">${esc(t)}</a>`).join(", ")}`;
  el.append(note);
}

function addAgent(id, agent = null) {
  const el = document.createElement("div");
  el.className = "turn agent";
  el.dataset.id = id || "";
  const label = agent ? `<div class="agent-label">${ICONS.agent}@${esc(agent)}</div>` : "";
  el.innerHTML = `${label}<div class="md"></div><ol class="steps"></ol><div class="receipt"></div>`;
  thread.append(el);
  updateEmpty();
  markLast();
  return el;
}

function markLast() {
  const agents = $$(".turn.agent", thread);
  agents.forEach((a, i) => {
    a.classList.toggle("last", i === agents.length - 1);
    // Messwerte nur am Ende eines Agent-Laufs, nicht nach jedem Zwischenschritt
    a.classList.toggle("end", !a.nextElementSibling?.classList.contains("agent"));
  });
}

function setThinking(el, text, streaming) {
  let det = $(".thinking", el);
  if (!det) {
    det = document.createElement("details");
    det.className = "thinking";
    det.innerHTML = `<summary>${ICONS.chevron}<span></span></summary><div class="think-body"></div>`;
    el.prepend(det);
  }
  $("summary span", det).textContent = streaming ? "Denkt nach …" : "Gedankengang";
  $(".think-body", det).textContent = text;
}

function setReceipt(el, s) {
  if (!s) return;
  const parts = [];
  if (s.tokens_per_s) parts.push(`${nf.format(s.tokens_per_s)} tok/s`);
  if (s.tokens) parts.push(`${s.tokens} Token`);
  if (s.total_s) parts.push(`${nf.format(s.total_s)} s`);
  if (s.prompt_tokens) parts.push(`Prompt ${nf.format(s.prompt_tokens)}`);
  if (s.load_s > 0.3) parts.push(`geladen in ${nf.format(s.load_s)} s`);
  let html = parts.map((p) => `<span>${esc(p)}</span>`).join("");
  if (s.done_reason === "length") html += `<span class="warn">Abgeschnitten – Kontext voll</span>`;
  if (el.raw?.trim()) html += `<button type="button" class="receipt-copy" data-copy-answer>Kopieren</button>`;
  $(".receipt", el).innerHTML = html;
}

function addStep(parent, { id, name, summary, args = {} }) {
  if (name === "todo_write") return null; // die Aufgabenliste hat ihre eigene Karte über der Eingabe
  const controlled = name === "controller";
  const agent = name === "agent" || controlled;
  const el = document.createElement("li");
  el.className = `step running${agent ? " open" : ""}`;
  el.dataset.name = name;
  // Ein Sub-Agent zeigt seinen Namen und die Aufgabe; seine eigenen Schritte erscheinen eingerückt darunter.
  const label = controlled ? "Kontrolle"
    : agent ? `@${args.agent || String(summary).split(" · ")[0]}` : (TOOL_VERB[name] || name).replace(/:$/, "");
  const target = controlled ? [args.model, summary].filter(Boolean).join(" · ")
    : agent ? args.task || String(summary).split(" · ").slice(1).join(" · ") : summary;
  const body = agent
    ? `<div class="step-body agent-body"><ol class="steps sub-steps"></ol><div class="agent-live"></div><div class="agent-report md" hidden></div></div>`
    : `<div class="step-body" hidden></div>`;
  el.innerHTML = `
    <button class="step-head${agent ? " expandable" : ""}" type="button" aria-expanded="${agent}">
      <span class="step-dot">${ICONS[name] || ICONS.run_command}<span class="step-badge" hidden></span></span>
      <span class="step-label">${esc(label)}</span>
      <span class="step-target">${esc(target)}</span>
      <span class="step-stat"></span>
      <span class="step-chev">${ICONS.chevron}</span>
    </button>
    ${body}`;
  $(".step-head", el).addEventListener("click", () => toggleStep(el));
  $(".steps", parent).append(el);
  state.tools.set(id, el);
  return el;
}

function toggleStep(el, open) {
  const body = $(".step-body", el);
  if (!body.innerHTML) return;
  const next = open ?? body.hidden;
  body.hidden = !next;
  el.classList.toggle("open", next);
  $(".step-head", el).setAttribute("aria-expanded", String(next));
}

function finishStep(el, { ok, output, display = {} }) {
  if (!el) return;
  el.classList.remove("running", "waiting");
  el.classList.add(ok ? "ok" : "fail");
  const badge = $(".step-badge", el);
  badge.hidden = false;
  badge.innerHTML = ok ? ICONS.check : ICONS.cross;

  const name = el.dataset.name;
  if (name === "agent" || name === "controller") return finishAgent(el, display);
  $(".step-label", el).textContent = TOOL_LABEL[name] || name;
  const stat = $(".step-stat", el);
  if (display.denied) stat.textContent = "Abgelehnt";
  else if (display.diff !== undefined) stat.innerHTML = `<span class="add">+${display.added || 0}</span> <span class="rem">−${display.removed || 0}</span>`;
  else if ((name === "read_file" || name === "memory_read") && display.lines !== undefined) stat.textContent = `${display.lines} Zeilen`;
  else if (name === "list_dir" && display.count !== undefined) stat.textContent = `${display.count} Einträge`;
  else if (name === "web_research" && display.count !== undefined) stat.textContent = `${display.count} ${display.count === 1 ? "Quelle" : "Quellen"}`;
  else if (name === "view_image" && display.model) stat.textContent = `mit ${display.model}`;
  else if (display.count !== undefined) stat.textContent = `${display.count} Treffer`;
  else if (display.chars !== undefined) stat.textContent = `${nf.format(display.chars)} Zeichen`;
  else if (display.background) stat.textContent = display.exit_code == null ? `Läuft · PID ${display.pid}` : `Beendet · Exit ${display.exit_code}`;
  else if (display.timed_out) stat.textContent = "Zeitüberschreitung";
  else if (display.exit_code !== undefined) stat.textContent = display.exit_code === 0 ? "Erfolgreich" : `Exit ${display.exit_code}`;

  const body = $(".step-body", el);
  if (display.diff) {
    body.innerHTML = diffHtml(display.diff);
    toggleStep(el, display.diff.split("\n").length <= 40);
  } else if (output) {
    body.innerHTML = `<pre>${esc(output)}</pre>`;
    if (name === "run_command" && !ok && !display.denied) toggleStep(el, true);
  }
  $(".step-head", el).classList.toggle("expandable", !!body.innerHTML);
}

function finishAgent(el, display) {
  const body = $(".agent-body", el);
  const steps = display.steps || [];
  // Nach dem Neuladen gibt es keine Live-Schritte – dann aus dem gespeicherten Verlauf aufbauen.
  if (!$(".step", body)) for (const s of steps) finishStep(addStep(body, s), s);
  $$(".step.running, .step.waiting", body).forEach((s) => finishStep(s, { ok: false }));
  $(".agent-live", body).textContent = "";
  const report = $(".agent-report", body);
  report.innerHTML = display.report ? markdown(display.report) : "<p>Kein Bericht – der Agent wurde vorher beendet.</p>";
  report.hidden = false;
  const count = steps.filter((s) => s.name !== "todo_write").length;
  $(".step-stat", el).textContent = [
    count ? `${count} ${count === 1 ? "Schritt" : "Schritte"}` : "",
    display.seconds ? duration(Math.round(display.seconds)) : "",
  ].filter(Boolean).join(" · ");
}

const VERDICT = {
  done: ["Passt", "check"], continue: ["Nachbessern", "redo"], unclear: ["Kein klares Urteil", "alert"],
  error: ["Fehlgeschlagen", "alert"], stopped: ["Abgelehnt", "cross"],
};
const REASON = { end: "prüft das Ergebnis", interval: "schaut nach dem Rechten", stuck: "hilft aus der Sackgasse" };

function addController(ev) {
  const turn = addAgent("");
  turn.classList.add("control");
  return addStep(turn, { id: ev.id, name: "controller", summary: REASON[ev.reason] || "", args: { model: ev.model } });
}

function finishController(el, d) {
  if (!el) return;
  const [label, icon] = VERDICT[d.verdict] || VERDICT.unclear;
  finishStep(el, { ok: d.verdict === "done", display: { ...d, report: d.note || label } });
  el.classList.remove("ok", "fail");
  el.classList.add(`verdict-${d.verdict}`);
  $(".step-badge", el).innerHTML = ICONS[icon];
  const stat = $(".step-stat", el);
  stat.textContent = [label, stat.textContent].filter(Boolean).join(" · ");
  if (d.verdict === "done") toggleStep(el, false); // Abgesegnetes nimmt keinen Platz weg
}

function addError(message) {
  const el = document.createElement("div");
  el.className = "notice-error";
  el.setAttribute("role", "alert");
  el.innerHTML = `${ICONS.alert}<div><strong>Das hat nicht geklappt</strong>${esc(message)}</div>`;
  thread.append(el);
  updateEmpty();
  scrollDown(true);
}

function addNotice(text) {
  const el = document.createElement("div");
  el.className = "notice";
  el.textContent = text;
  thread.append(el);
  updateEmpty();
  scrollDown();
}

function addCompacted(summary) {
  const el = document.createElement("details");
  el.className = "compacted";
  el.innerHTML = `<summary>Verlauf verdichtet – Zusammenfassung anzeigen</summary><div class="md">${markdown(summary || "")}</div>`;
  thread.append(el);
  updateEmpty();
}

/* Geänderte Dateien eines Auftrags – die jüngsten lassen sich zurücknehmen */
function addChanges(ch) {
  if (!ch?.files?.length) return null;
  const el = document.createElement("div");
  el.className = `changes${ch.undone ? " undone" : ""}`;
  el.dataset.turn = ch.turn;
  const total = (key) => ch.files.reduce((n, f) => n + (f[key] || 0), 0);
  const count = ch.files.length;
  const rows = ch.files.slice(0, 8).map((f) => {
    const tag = f.created ? "neu" : f.deleted ? "gelöscht" : "";
    const stat = f.added == null ? "" : `<span class="add">+${f.added}</span> <span class="rem">−${f.removed}</span>`;
    return `<li><span class="changes-path" title="${esc(f.path)}">${esc(ltr(f.path))}</span>` +
      `${tag ? `<span class="changes-tag">${tag}</span>` : ""}<span class="changes-stat">${stat}</span></li>`;
  }).join("");
  const more = count > 8 ? `<li class="more">und ${count - 8} weitere</li>` : "";
  el.innerHTML = `
    <div class="changes-head">
      <span class="changes-icon">${ICONS.edit_file}</span>
      <span class="changes-title">${count} ${count === 1 ? "Datei" : "Dateien"} geändert</span>
      <span class="changes-sum"><span class="add">+${total("added")}</span> <span class="rem">−${total("removed")}</span></span>
      <span class="spacer"></span>
      <span class="changes-state">Zurückgenommen</span>
      <button type="button" class="btn ghost" data-undo title="Stellt die Dateien wie vor diesem Auftrag wieder her. Befehle im Terminal lassen sich nicht zurücknehmen.">${ICONS.undo}<span>Rückgängig</span></button>
    </div>
    <ul class="changes-files">${rows}${more}</ul>`;
  thread.append(el);
  updateEmpty();
  updateUndo();
  return el;
}

// Zurückgenommen wird immer der jüngste Auftrag zuerst – nur dort steht der Knopf.
function updateUndo() {
  const latest = $$(".changes", thread).reverse().find((b) => !b.classList.contains("undone"));
  $$(".changes", thread).forEach((b) => b.classList.toggle("undoable", b === latest && !state.busy));
}

function addUndoNotice(result) {
  const restored = result.restored || [];
  const skipped = result.skipped || [];
  let text = restored.length
    ? `Zurückgenommen: ${restored.slice(0, 6).join(", ")}${restored.length > 6 ? ` und ${restored.length - 6} weitere` : ""}.`
    : "Nichts zurückzunehmen – die Dateien waren schon im alten Zustand.";
  if (skipped.length) text += ` Nicht angefasst: ${skipped.map((s) => `${s.path} (${s.reason})`).join(", ")}.`;
  addNotice(text);
}

function undoLast() {
  if (state.busy) return toast("Erst den laufenden Auftrag stoppen, dann zurücknehmen.");
  const button = $(".changes.undoable [data-undo]", thread);
  if (button) button.disabled = true;
  send({ type: "undo" });
  clearTimeout(undoLast.timer);
  undoLast.timer = setTimeout(() => { // ein älterer Server kennt „undo“ noch nicht
    if (!button?.disabled) return;
    button.disabled = false;
    toast("Coder hat nicht geantwortet – nach einem Neustart von Coder klappt das.", { error: true });
  }, 8000);
}

/* Nachrichten während der Arbeit warten über der Eingabe, bis der Agent sie vor seinem nächsten Schritt liest. */
const queue = []; // { id, text, confirmed, timer }

function renderQueue() {
  const box = $("#queue");
  box.hidden = !queue.length;
  box.innerHTML = queue.map((q) => `
    <div class="queue-item${q.confirmed ? "" : " pending"}">
      <span class="queue-label">Wartet</span>
      <span class="queue-text" title="${esc(q.text)}">${esc(q.text)}</span>
      <button type="button" class="icon-btn" data-unqueue="${esc(q.id)}" aria-label="Zurückziehen" title="Zurückziehen – der Text kommt zurück in die Eingabe">${ICONS.cross}</button>
    </div>`).join("");
}

async function queueMessage() {
  const text = input.value.trim();
  if (!text) return;
  if (attachments.length) return toast("Bilder lassen sich erst anhängen, wenn der Agent fertig ist.");
  let prompt = text;
  if (text.startsWith("/")) {
    const head = text.split(/\s+/)[0];
    const name = head.slice(1).toLowerCase();
    if (BUILTIN_COMMANDS.some((c) => c.name === (COMMAND_ALIASES[name] || name))) return toast("Das geht, sobald der Agent fertig ist.");
    const custom = (await loadExtensions().catch(() => null))?.commands.find((c) => c.name === name);
    if (custom) prompt = expandCommand(custom, text.slice(head.length).trim());
  }
  const item = { id: `q${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`, text, confirmed: false };
  queue.push(item);
  renderQueue();
  hideSuggest();
  clearInput();
  send({ type: "send", text: prompt, ...(prompt === text ? {} : { display: text }), queue_id: item.id });
  item.timer = setTimeout(() => {
    if (!item.confirmed) dropQueued([item], "Coder hat die Nachricht nicht angenommen – sie steht wieder in der Eingabe.");
  }, 5000);
}

function takeFromQueue(id) {
  const at = queue.findIndex((q) => q.id === id);
  if (at < 0) return null;
  const [item] = queue.splice(at, 1);
  clearTimeout(item.timer);
  renderQueue();
  return item;
}

// Nicht gelesene Nachrichten gehen nie verloren: Sie kommen zurück in die Eingabe.
function dropQueued(items, message) {
  const texts = items.map((it) => takeFromQueue(it.id)?.text ?? it.display ?? it.text).filter(Boolean);
  if (!texts.length) return;
  input.value = [...texts, input.value.trim()].filter(Boolean).join("\n\n");
  autosize();
  updateSendState();
  if (message) toast(message);
}

function sessionMarkdown(s) {
  const out = [`# ${s.title || "Chat"}`, "", `Workspace: \`${s.workspace}\``, ""];
  for (const m of s.messages || []) {
    if (m.role === "user" && !m._nudge && !m._controller && !m._summary) {
      out.push("## Du", "", m._text ?? m.content, "");
    } else if (m.role === "assistant" && !m._quiet) {
      const text = (m._shown ?? m.content ?? "").trim();
      const calls = (m._calls || []).filter((c) => c.name !== "todo_write").map((c) => `- ${TOOL_LABEL[c.name] || c.name}: \`${summaryOf(c)}\``);
      if (text || calls.length) out.push("## Coder", "", ...(text ? [text, ""] : []), ...(calls.length ? [...calls, ""] : []));
    } else if (m._changes) {
      out.push(`_${m._changes.files.length} Dateien geändert: ${m._changes.files.map((f) => f.path).join(", ")}${m._changes.undone ? " (zurückgenommen)" : ""}_`, "");
    } else if (m._controller && m.role === "event") {
      out.push(`_Kontrolle (${m._controller.model}): ${m._controller.note || m._controller.verdict}_`, "");
    }
  }
  return out.join("\n");
}

async function copyChat() {
  if (!state.session?.id) return;
  try {
    await copyText(sessionMarkdown(await api(`/api/sessions/${state.session.id}`)));
    toast("Chat als Markdown kopiert");
  } catch (e) {
    toast(state.session.messages?.length || state.busy ? "Der Chat wird erst nach dem Auftrag gespeichert." : "Der Chat ist noch leer.", { error: true });
  }
}

function summaryOf(call) {
  const a = call.args || {};
  return a.path || a.pattern || a.command || a.query || a.url || (a.todos ? `${a.todos.length} Aufgaben` : "");
}

function renderSession(s) {
  thread.classList.add("instant");
  thread.innerHTML = "";
  state.tools.clear();
  state.live = null;
  let lastAgent = null;
  let labeled = null; // der @Agent eines Auftrags steht nur über seiner ersten Antwort
  for (const m of s.messages || []) {
    if (m.role === "event") {
      if (m._controller) finishController(addController(m._controller), m._controller);
      if (m._changes) addChanges(m._changes);
      if (m._undo) addUndoNotice(m._undo);
    } else if (m.role === "user") {
      if (m._nudge || m._controller) continue; // interne Nachfragen an das Modell, nicht vom Nutzer
      labeled = null;
      if (m._summary) addCompacted(m.content.replace(/^\[.*?\]\n/, ""));
      else {
        const el = addUser(m._text ?? m.content, m._images || []);
        addVisionNote(el, m._vision);
        addRecallNote(el, m._recall);
      }
    } else if (m.role === "assistant") {
      if (m._quiet) continue;
      const el = addAgent(m._id, m._agent && m._agent !== labeled ? m._agent : null);
      labeled = m._agent || labeled;
      if (m._thinking) setThinking(el, m._thinking, false);
      el.raw = m._shown ?? m.content;
      $(".md", el).innerHTML = markdown(el.raw);
      for (const c of m._calls || []) addStep(el, { ...c, summary: summaryOf(c) });
      setReceipt(el, m._stats);
      lastAgent = el;
    } else if (m.role === "tool") {
      let step = state.tools.get(m._id);
      if (!step && lastAgent) step = addStep(lastAgent, { id: m._id, name: m._name, summary: m._summary || "", args: m._display || {} });
      finishStep(step, { ok: m._ok, output: m.content, display: m._display || {} });
    }
  }
  state.tools.forEach((el) => { if (el.classList.contains("running")) finishStep(el, { ok: false }); });
  markLast();
  updateUndo();
  renderTodos(s.todos || []);
  updateEmpty();
  updateTitle();
  if (thread.childElementCount) scrollDown(true);
  else scroller.scrollTop = 0; // leerer Chat: die Startseite von oben zeigen, nicht an ihr Ende springen
  requestAnimationFrame(() => requestAnimationFrame(() => thread.classList.remove("instant")));
}

function renderTodos(todos) {
  const el = $("#todos");
  const done = todos.filter((t) => t.status === "completed").length;
  if (!todos.length || (done === todos.length && !state.busy)) {
    el.hidden = true;
    return;
  }
  el.innerHTML = `
    <div class="todos-head">
      <span class="eyebrow">Aufgaben</span>
      <span class="todos-bar"><i style="width:${(done / todos.length) * 100}%"></i></span>
      <span class="todos-count">${done} von ${todos.length}</span>
    </div>
    <ul class="todo-list">${todos.map((t) =>
      `<li class="todo ${t.status}"><i>${t.status === "completed" ? ICONS.check : ""}</i><span>${esc(t.content)}</span></li>`).join("")}
    </ul>`;
  el.hidden = false;
}

function updateTitle() {
  const title = state.session?.title && state.session.title !== "Neuer Chat" ? state.session.title : "";
  $("#chatTitle").textContent = title || "Neuer Chat";
  document.title = title ? `${title} – Coder` : "Coder";
}

/* ================================================================ Agent Island */

const activity = { start: 0, timer: null, steps: 0 };

function startActivity() {
  activity.start = Date.now();
  activity.steps = 0;
  $("#activity").hidden = false;
  setActivity("Denkt nach …");
  tickActivity();
  clearInterval(activity.timer);
  activity.timer = setInterval(tickActivity, 1000);
}

function tickActivity() {
  const secs = Math.round((Date.now() - activity.start) / 1000);
  const steps = activity.steps ? ` · ${activity.steps} ${activity.steps === 1 ? "Schritt" : "Schritte"}` : "";
  $("#activityMeta").textContent = duration(secs) + steps;
}

function setActivity(text, icon) {
  $("#activity").classList.toggle("waiting", icon === "alert");
  $("#activityText").textContent = text;
  $("#activityIcon").innerHTML = icon && ICONS[icon] ? ICONS[icon] : `<span class="spinner"></span>`;
}

function stopActivity() {
  clearInterval(activity.timer);
  $("#activity").hidden = true;
}

function alwaysButton(req) {
  if (req.always === null) return ""; // verkettete Befehle oder rm & Co. fragen jedes Mal
  const command = req.name === "run_command" && req.always;
  const label = command ? `Immer: ${req.always}` : "Immer erlauben";
  const title = command ? `Befehle, die mit „${req.always}“ beginnen, laufen in diesem Chat ohne Rückfrage`
    : "Diese Art von Aktion läuft in diesem Chat ohne Rückfrage";
  return `<button type="button" class="btn approval-always" data-d="always" title="${esc(title)}"><span>${esc(label)}</span></button>`;
}

function showApproval(req) {
  state.approvalId = req.id;
  const step = state.tools.get(req.id);
  if (step) {
    step.classList.remove("running");
    step.classList.add("waiting");
    const host = step.parentElement.closest('.step[data-name="agent"]');
    if (host) toggleStep(host, true); // die wartende Aktion eines Sub-Agents sichtbar machen
  }
  const box = $("#approval");
  const preview = req.preview?.diff ? `<div class="approval-preview">${diffHtml(req.preview.diff)}</div>` : "";
  box.innerHTML = `
    <div class="approval-head">
      <span class="approval-icon">${ICONS[req.name] || ICONS.alert}</span>
      <div class="approval-copy">
        ${req.agent ? `<div class="approval-agent">${esc(agentName(req.agent))} möchte</div>` : ""}
        <div class="approval-title">${esc(APPROVAL_TITLE[req.name] || `${req.name} ausführen?`)}</div>
        <code class="approval-target">${esc(req.summary)}</code>
      </div>
    </div>
    ${preview}
    <div class="approval-actions">
      <button type="button" class="btn ghost" data-d="deny">Ablehnen <kbd>Esc</kbd></button>
      <span class="spacer"></span>
      ${alwaysButton(req)}
      <button type="button" class="btn primary" data-d="allow">Erlauben <kbd>Strg ⏎</kbd></button>
    </div>`;
  $$("[data-d]", box).forEach((b) => b.addEventListener("click", () => answerApproval(b.dataset.d)));
  box.hidden = false;
  setActivity("Wartet auf deine Freigabe", "alert");
}

function answerApproval(decision) {
  if (!state.approvalId) return;
  send({ type: "permission", id: state.approvalId, decision });
  const step = state.tools.get(state.approvalId);
  if (step && decision !== "deny") {
    step.classList.remove("waiting");
    step.classList.add("running");
  }
  hideApproval();
  setActivity(decision === "deny" ? "Abgelehnt" : "Wird ausgeführt …");
}

function hideApproval() {
  state.approvalId = null;
  const box = $("#approval");
  box.hidden = true;
  box.innerHTML = "";
}

/* ================================================================ Live-Stream */

function queueRender() {
  if (state.renderQueued) return;
  state.renderQueued = true;
  // Höchstens ~15 Mal pro Sekunde neu setzen: weniger Umbruch-Flackern, Text und Knöpfe bleiben greifbar.
  setTimeout(() => requestAnimationFrame(() => {
    state.renderQueued = false;
    const live = state.live;
    if (!live) return;
    const md = $(".md", live.el);
    md.innerHTML = markdown(live.text);
    const last = md.lastElementChild;
    if (last && !last.classList.contains("code")) last.classList.add("cursor");
    if (live.thinking) setThinking(live.el, live.thinking, !live.text);
    scrollDown();
  }), 60);
}

const handlers = {
  session(ev) {
    if (ev.session.workspace !== state.session?.workspace) state.ext = null; // Agents hängen am Ordner
    for (const q of queue.splice(0)) clearTimeout(q.timer);
    renderQueue();
    state.session = ev.session;
    store.set("coder.session", ev.session.id);
    hideApproval();
    renderSession(ev.session);
    renderSessions();
    updateWorkspace();
    setContext(null);
  },
  busy(ev) { setBusy(ev.busy); },
  status(ev) {
    setActivity(ev.text);
    setModelDot("busy");
  },
  model(ev) {
    state.plan = ev.plan;
    state.config.model = ev.model;
    const actual = ev.plan.actual;
    if (actual) state.loaded = [actual, ...state.loaded.filter((m) => m.name !== actual.name)];
    updateModelPill();
    updateStart();
  },
  profile(ev) { state.runAgent = ev.agent; },
  assistant_start(ev) {
    const label = state.runAgent && !state.runLabeled ? state.runAgent : null;
    state.runLabeled = state.runLabeled || !!label;
    state.live = { id: ev.id, el: addAgent(ev.id, label), text: "", thinking: "" };
    setActivity("Denkt nach …");
    scrollDown();
  },
  thinking(ev) {
    if (!state.live) return;
    state.live.thinking += ev.text;
    queueRender();
  },
  text(ev) {
    if (!state.live) return;
    if (!state.live.text) setActivity("Schreibt …");
    state.live.text += ev.text;
    queueRender();
  },
  stats(ev) {
    const live = state.live;
    if (!live) return;
    live.el.raw = live.text;
    $(".md", live.el).innerHTML = markdown(live.text);
    if (live.thinking) setThinking(live.el, live.thinking, false);
    setReceipt(live.el, ev.stats);
    markLast();
  },
  tool_call(ev) {
    const parent = state.live?.el || addAgent("");
    addStep(parent, ev);
    if (ev.name !== "todo_write") activity.steps++;
    tickActivity();
    if (ev.name === "agent") setActivity(`@${ev.args.agent} übernimmt`, "agent");
    else setActivity(`${TOOL_VERB[ev.name] || ev.name} ${ev.name === "todo_write" ? "" : ev.summary}`.trim(), ev.name);
    scrollDown();
  },
  permission(ev) { showApproval(ev); },
  tool_running() { },
  tool_result(ev) {
    finishStep(state.tools.get(ev.id), ev);
    if (state.approvalId === ev.id) hideApproval();
    if (ev.name === "memory_write") memoryUI.data = null; // neue Notiz: Liste und Vorschläge frisch laden
    setActivity("Denkt nach …");
    scrollDown();
  },
  todos(ev) {
    state.session.todos = ev.todos;
    renderTodos(ev.todos);
  },
  context(ev) { setContext(ev); },
  compacted(ev) { addCompacted(ev.summary); },
  notice(ev) { addNotice(ev.text); },
  error(ev) { addError(ev.message); },
  controller(ev) {
    if (ev.state === "start") {
      state.live = null; // die nächste Antwort beginnt unter der Prüfung
      addController(ev);
      setActivity(`Kontrolle · ${ev.model} ${REASON[ev.reason] || "prüft"} …`, "controller");
    } else {
      finishController(state.tools.get(ev.id), ev);
      setActivity("Denkt nach …");
    }
    markLast();
    scrollDown();
  },
  recall(ev) { addRecallNote(lastUserTurn(), ev.notes); },
  vision(ev) { addVisionNote(lastUserTurn(), ev); },
  watchdog(ev) {
    addNotice(ev.text);
    setActivity(ev.text, "alert");
  },
  assistant_discard(ev) {
    if (state.live?.id !== ev.id) return;
    state.live.el.remove();
    state.live = null;
    markLast();
  },
  memory_changed() { memoryUI.data = null; },
  // Werkzeugaufrufe, die das Modell als Text geschrieben hat, verschwinden aus der Antwort
  assistant_text(ev) {
    if (state.live?.id !== ev.id) return;
    state.live.text = ev.text;
    queueRender();
  },
  changes(ev) {
    addChanges(ev);
    markLast();
    scrollDown();
  },
  undone(ev) {
    clearTimeout(undoLast.timer);
    const block = $$(".changes", thread).find((b) => b.dataset.turn === ev.turn);
    if (block) {
      block.classList.add("undone");
      $("[data-undo]", block).disabled = false;
    }
    addUndoNotice(ev);
    updateUndo();
    scrollDown();
  },
  undo_failed(ev) {
    clearTimeout(undoLast.timer);
    $$(".changes [data-undo]", thread).forEach((b) => (b.disabled = false));
    toast(ev.message, { error: true });
  },
  queued(ev) {
    const item = queue.find((q) => q.id === ev.id);
    if (!item) return;
    item.confirmed = true;
    clearTimeout(item.timer);
    renderQueue();
  },
  queue_rejected(ev) {
    const item = queue.find((q) => q.id === ev.id);
    if (item) dropQueued([item], ev.message);
  },
  queued_taken(ev) {
    const item = takeFromQueue(ev.id);
    addUser(item?.text ?? ev.text);
    markLast();
    scrollDown(true);
  },
  unqueued(ev) {
    if (!ev.ok) toast("Zu spät – der Agent hatte die Nachricht schon gelesen.");
  },
  queue_dropped(ev) {
    dropQueued(ev.items || [], "Nicht gesendet – die Nachricht steht wieder in der Eingabe.");
  },
  done(ev) {
    setBusy(false);
    hideApproval();
    state.runAgent = null;
    state.runLabeled = false;
    const md = state.live && $(".md", state.live.el);
    if (md) $$(".cursor", md).forEach((n) => n.classList.remove("cursor"));
    state.live = null;
    state.tools.forEach((el) => { if (el.classList.contains("running") || el.classList.contains("waiting")) finishStep(el, { ok: false }); });
    $$(".turn.agent", thread).forEach((a) => { if (!a.textContent.trim() && !$(".step", a)) a.remove(); });
    markLast();
    if (state.session && ev.session) state.session.title = ev.session.title;
    updateTitle();
    refreshSessions();
    refreshLoaded();
    renderTodos(state.session?.todos || []);
    updateUndo();
  },
};

/* Ereignisse eines Sub-Agents landen eingerückt in seinem Schritt statt im Hauptverlauf. */
const subHandlers = {
  assistant_start(ev, host) {
    host.dataset.live = "";
    $(".agent-live", host).textContent = "";
  },
  text(ev, host) {
    host.dataset.live = (host.dataset.live || "").slice(-2000) + ev.text;
    $(".agent-live", host).textContent = host.dataset.live.replace(/\s+/g, " ").trim().slice(-160);
  },
  tool_call(ev, host) {
    addStep($(".agent-body", host), ev);
    const count = $$(".sub-steps > .step", host).length;
    $(".step-stat", host).textContent = `${count} ${count === 1 ? "Schritt" : "Schritte"}`;
    $(".agent-live", host).textContent = "";
    if (ev.name !== "todo_write") activity.steps++;
    tickActivity();
    setActivity(`${agentName(ev.agent)} · ${TOOL_VERB[ev.name] || ev.name} ${ev.summary}`.trim(), ev.name);
    scrollDown();
  },
  tool_result(ev) {
    finishStep(state.tools.get(ev.id), ev);
    if (state.approvalId === ev.id) hideApproval();
    if (ev.name === "memory_write") memoryUI.data = null;
    setActivity(`${agentName(ev.agent)} arbeitet …`, ev.agent === "kontrolle" ? "controller" : "agent");
    scrollDown();
  },
  status(ev) { setActivity(`${agentName(ev.agent)} · ${ev.text}`); },
};

/* ================================================================ WebSocket */

let reconnectDelay = 800;
function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  state.ws = ws;
  ws.onopen = () => {
    reconnectDelay = 800;
    send({ type: "open", session_id: state.session?.id || store.get("coder.session") });
  };
  ws.onmessage = (e) => {
    const ev = JSON.parse(e.data);
    if (ev.parent) {
      const host = state.tools.get(ev.parent);
      if (host) subHandlers[ev.type]?.(ev, host);
      return;
    }
    handlers[ev.type]?.(ev);
  };
  ws.onclose = () => {
    setBusy(false);
    if (queue.length) dropQueued([...queue], "Verbindung unterbrochen – die Nachricht steht wieder in der Eingabe.");
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.6, 8000);
  };
}

function send(msg) {
  if (state.ws?.readyState === WebSocket.OPEN) state.ws.send(JSON.stringify(msg));
  else toast("Keine Verbindung zum Coder-Server.", { error: true });
}

/* ================================================================ Toolbar & Status */

function setBusy(busy) {
  state.busy = busy;
  $("#app").classList.toggle("busy", busy);
  $("#sendBtn").setAttribute("aria-label", busy ? "Stoppen" : "Senden");
  $("#sendBtn").title = busy ? "Stoppen (Esc)" : "Senden (Enter)";
  if (busy) startActivity();
  else stopActivity();
  updateSendState();
  updatePlaceholder();
  updateUndo();
  if (!busy) updateModelPill();
}

function setContext(ev) {
  const meter = $("#ctxMeter");
  if (!ev || !ev.max) {
    $("#ctxBar").style.strokeDashoffset = 50.27;
    $("#ctxText").textContent = "Kontext";
    meter.classList.remove("high");
    meter.title = "Kontextauslastung – wird nach der ersten Antwort gemessen";
    return;
  }
  const ratio = Math.min(1, ev.used / ev.max);
  $("#ctxBar").style.strokeDashoffset = 50.27 * (1 - ratio);
  $("#ctxText").textContent = `${pct(ratio)} von ${kctx(ev.max)}`;
  meter.classList.toggle("high", ratio > 0.7);
  meter.title = `${nf.format(ev.used)} von ${nf.format(ev.max)} Token · verdichtet automatisch ab 80 %`;
}

function setModelDot(cls) {
  $("#modelDot").className = `dot ${cls || ""}`;
}

function liveModel() {
  return state.loaded.find((m) => m.name === state.config?.model);
}

function updateModelPill() {
  const model = state.config?.model;
  $("#modelName").textContent = model || "Modell wählen";
  const live = liveModel();
  if (state.ollama && !state.ollama.ok) {
    setModelDot("off");
    $("#modelMeta").textContent = "Ollama offline";
  } else if (live) {
    const ctx = live.context_length || state.plan?.num_ctx;
    setModelDot(live.gpu_share >= 0.999 ? "ok" : "warn");
    $("#modelMeta").textContent = `${ctx ? kctx(ctx) + " · " : ""}${pct(live.gpu_share)} GPU`;
  } else {
    setModelDot("");
    $("#modelMeta").textContent = model ? "nicht geladen" : "";
  }
}

function updateStart() {
  const ws = currentWorkspace();
  $("#startTitle").textContent = basename(ws) || "Coder";
  $("#startPath").textContent = ltr(ws);
  $("#startPath").title = ws;
  const status = $("#startStatus");
  const live = liveModel();
  const model = state.config?.model;
  let dot = "", text;
  if (state.ollama && !state.ollama.ok) {
    dot = "off";
    text = "Ollama ist nicht erreichbar – starte Ollama";
  } else if (live) {
    dot = live.gpu_share >= 0.999 ? "ok" : "warn";
    const ctx = live.context_length || state.plan?.num_ctx;
    text = `${model} · ${ctx ? kctx(ctx) + " Kontext · " : ""}${pct(live.gpu_share)} GPU`;
  } else if (model) {
    text = `${model} · lädt beim ersten Senden`;
  } else {
    text = "Das beste Modell wird automatisch gewählt";
  }
  status.innerHTML = `<span class="dot ${dot}"></span><span>${esc(text)}</span>`;
}

function activeThumbRect() {
  const seg = $("#modeSeg");
  const active = $("button.on", seg);
  if (!active) return null;
  const box = seg.getBoundingClientRect();
  const r = active.getBoundingClientRect();
  return { x: r.left - box.left, w: r.width };
}

let thumbRect = null;
let thumbFrame = 0;
function drawThumb(rect) {
  thumbRect = rect;
  $("#segThumb").style.width = `${rect.w}px`;
  $("#segThumb").style.transform = `translateX(${rect.x}px)`;
}

function setMode(mode, persist = true) {
  const seg = $("#modeSeg");
  const thumb = $("#segThumb");
  const start = thumbRect || activeThumbRect(); // wo der Regler gerade steht, auch mitten in einer Bewegung
  seg.dataset.mode = mode;
  cancelAnimationFrame(thumbFrame);
  thumb.style.transition = "none";
  seg.classList.toggle("instant", !persist); // Laden und Größenänderung: ohne Bewegung
  $$("button", seg).forEach((b) => {
    const on = b.dataset.mode === mode;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
  });
  if (persist && start) {
    // Der Regler gleitet vom alten zum neuen Modus, während sich die Namen öffnen und schließen.
    // Das Ziel wird jedes Bild neu gemessen, weil die Knöpfe dabei ihre Breite ändern.
    const t0 = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t0) / 480);
      const eased = 1 - (1 - p) ** 4;
      const to = activeThumbRect();
      drawThumb({ x: start.x + (to.x - start.x) * eased, w: start.w + (to.w - start.w) * eased });
      if (p < 1) thumbFrame = requestAnimationFrame(step);
      else thumb.style.transition = "";
    };
    thumbFrame = requestAnimationFrame(step);
  } else {
    drawThumb(activeThumbRect());
    void seg.offsetWidth;
    seg.classList.remove("instant");
    thumb.style.transition = "";
  }
  if (persist && state.config && state.config.permission_mode !== mode) {
    state.config.permission_mode = mode;
    api("/api/config", { method: "POST", body: { permission_mode: mode } })
      .then(() => { if (mode === "yolo") toast("Autonom: Befehle laufen ohne Rückfrage."); })
      .catch((e) => toast(e.message, { error: true }));
  }
}

function currentWorkspace() {
  // Der Agent arbeitet im Ordner des offenen Chats; neue Chats übernehmen den gewählten Workspace.
  return state.session?.workspace || state.config?.workspace || "";
}

function updateWorkspace() {
  const ws = currentWorkspace();
  const name = basename(ws);
  const title = `Workspace ändern (Strg+O)\n${ws}`;
  $("#workspaceName").textContent = name || "Workspace";
  $("#workspacePath").textContent = ltr(ws);
  $("#workspaceBtn").title = title;
  $("#wsChipName").textContent = name || "Workspace";
  $("#wsChip").title = title;
  $("#settingsWsPath").textContent = ltr(ws);

  const hw = state.hardware;
  const parts = [];
  if (hw?.gpus?.length) parts.push(`${hw.gpus[0].name.replace(/^NVIDIA (GeForce )?/, "")} · ${gb(hw.vram_total)}`);
  else if (hw) parts.push("CPU");
  if (state.ollama) parts.push(state.ollama.ok ? `Ollama ${state.ollama.version}` : "Ollama offline");
  $("#hwHint").textContent = parts.join(" · ");
  updateStart();
}

async function refreshLoaded() {
  try {
    const data = await api("/api/loaded");
    state.loaded = data.loaded;
    state.hardware = data.hardware;
    if (!state.busy && !state.modelLoading) { // sonst überschreibt die Abfrage „wird geladen …“
      updateModelPill();
      updateStart();
    }
  } catch { /* Server kurz weg */ }
}

/* ================================================================ Sidebar */

async function refreshSessions() {
  try {
    state.sessions = await api("/api/sessions");
    renderSessions();
  } catch { /* ignorieren */ }
}

function renderSessions() {
  const list = $("#sessionList");
  const q = $("#search").value.trim().toLowerCase();
  const startOfDay = new Date().setHours(0, 0, 0, 0) / 1000;
  const groups = [["Heute", startOfDay], ["Gestern", startOfDay - 86400], ["Letzte 7 Tage", startOfDay - 6 * 86400], ["Älter", -Infinity]];
  const buckets = groups.map(() => []);
  for (const s of state.sessions) {
    if (q && !`${s.title} ${s.workspace}`.toLowerCase().includes(q)) continue;
    buckets[groups.findIndex(([, t]) => s.updated >= t)].push(s);
  }
  list.innerHTML = "";
  buckets.forEach((items, gi) => {
    if (!items.length) return;
    const head = document.createElement("div");
    head.className = "session-group eyebrow";
    head.textContent = groups[gi][0];
    list.append(head);
    for (const s of items) {
      const row = document.createElement("div");
      row.className = `session${state.session?.id === s.id ? " active" : ""}`;
      row.setAttribute("role", "button");
      row.tabIndex = 0;
      row.title = `${s.title}\n${s.workspace}`;
      const meta = [whenLabel(s.updated), basename(s.workspace), s.model].filter(Boolean).join(" · ");
      row.innerHTML = `
        <span class="session-text">
          <span class="session-title">${esc(s.title || "Ohne Titel")}</span>
          <span class="session-meta">${esc(meta)}</span>
        </span>
        <button class="icon-btn del" type="button" aria-label="Chat löschen" title="Löschen">${ICONS.trash}</button>`;
      row.addEventListener("click", (e) => {
        if (e.target.closest(".del")) return deleteSession(s);
        if (state.busy) return toast("Der Agent arbeitet noch.");
        send({ type: "open", session_id: s.id });
        $("#app").classList.remove("open");
      });
      row.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target === row) row.click(); });
      list.append(row);
    }
  });
  if (!list.childElementCount) {
    list.innerHTML = `<div class="session-empty">${q ? "Keine passenden Chats." : "Deine Chats erscheinen hier."}</div>`;
  }
}

async function deleteSession(s) {
  if (!confirm(`„${s.title}“ löschen?`)) return;
  try {
    await api(`/api/sessions/${s.id}`, { method: "DELETE" });
    if (state.session?.id === s.id) send({ type: "new" });
    refreshSessions();
  } catch (e) {
    toast(e.message, { error: true });
  }
}

/* ================================================================ Eingabe */

const input = $("#input");

function autosize() {
  input.style.height = "auto";
  // Leeres Feld nicht messen: Chromium zählt einen umbrechenden Placeholder mit.
  if (input.value) input.style.height = `${Math.min(input.scrollHeight, 240)}px`;
}
window.addEventListener("resize", autosize);

function updateSendState() {
  $("#sendBtn").disabled = !state.busy && !input.value.trim() && !attachments.some((a) => a.id);
}

/* ================================================================ Bilder anhängen */

const attachments = []; // { id, url, name, pending }
const MAX_IMAGES = 6;

async function imageData(file) {
  const bitmap = await createImageBitmap(file).catch(() => null);
  if (!bitmap) throw new Error(`${file.name || "Das Bild"} lässt sich nicht lesen.`);
  const scale = Math.min(1, 1568 / Math.max(bitmap.width, bitmap.height)); // mehr Details erkennen Bildmodelle nicht
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close?.();
  // Screenshots bleiben PNG – scharfe Schrift –, Fotos werden JPEG
  return canvas.toDataURL(file.type === "image/png" ? "image/png" : "image/jpeg", 0.9);
}

async function addImages(files) {
  const images = [...(files || [])].filter((f) => f.type.startsWith("image/"));
  for (const file of images) {
    if (attachments.length >= MAX_IMAGES) {
      toast(`Höchstens ${MAX_IMAGES} Bilder pro Nachricht.`);
      break;
    }
    const item = { id: null, url: URL.createObjectURL(file), name: file.name || "Bild", pending: true };
    attachments.push(item);
    renderAttachments();
    try {
      const saved = await api("/api/images", { method: "POST", body: { data: await imageData(file) } });
      item.id = saved.id;
    } catch (e) {
      const at = attachments.indexOf(item);
      if (at >= 0) attachments.splice(at, 1);
      URL.revokeObjectURL(item.url);
      toast(e.message, { error: true });
    }
    item.pending = false;
    renderAttachments();
  }
  if (images.length) input.focus();
  return images.length > 0;
}

function renderAttachments() {
  const box = $("#attachments");
  box.hidden = !attachments.length;
  box.innerHTML = attachments.map((a, i) => `
    <figure class="attachment${a.pending ? " pending" : ""}">
      <img src="${a.url}" alt="${esc(a.name)}">
      <button type="button" class="attachment-remove" data-remove="${i}" aria-label="${esc(a.name)} entfernen">${ICONS.cross}</button>
    </figure>`).join("");
  updateSendState();
}

$("#attachments").addEventListener("click", (e) => {
  const remove = e.target.closest("[data-remove]");
  if (!remove) return;
  const [item] = attachments.splice(Number(remove.dataset.remove), 1);
  if (item) URL.revokeObjectURL(item.url);
  renderAttachments();
  input.focus();
});
$("#attachBtn").addEventListener("click", () => $("#fileInput").click());
$("#fileInput").addEventListener("change", (e) => {
  addImages(e.target.files);
  e.target.value = "";
});
input.addEventListener("paste", (e) => {
  const files = [...(e.clipboardData?.files || [])];
  if (!files.some((f) => f.type.startsWith("image/"))) return;
  e.preventDefault();
  addImages(files);
});

thread.addEventListener("click", (e) => {
  const image = e.target.closest("[data-image]");
  if (!image) return;
  const box = $("#lightbox");
  $("img", box).src = `/api/images/${encodeURIComponent(image.dataset.image)}`;
  box.hidden = false;
});
$("#lightbox").addEventListener("click", () => { $("#lightbox").hidden = true; });
thread.addEventListener("click", (e) => { if (e.target.closest("[data-undo]")) undoLast(); });
$("#queue").addEventListener("click", (e) => {
  const button = e.target.closest("[data-unqueue]");
  const item = button && takeFromQueue(button.dataset.unqueue);
  if (!item) return;
  send({ type: "unqueue", id: item.id });
  input.value = [input.value.trim(), item.text].filter(Boolean).join("\n\n");
  autosize();
  updateSendState();
  input.focus();
});

const BUILTIN_COMMANDS = [
  { name: "new", description: "Neuer Chat", run: () => send({ type: "new" }) },
  { name: "compact", description: "Verlauf verdichten und Kontext freimachen", run: () => send({ type: "compact" }) },
  { name: "undo", description: "Dateiänderungen des letzten Auftrags zurücknehmen", run: () => undoLast() },
  { name: "agents", description: "Agents ansehen, anlegen und bearbeiten", run: () => openAgents() },
  { name: "memory", description: "Gedächtnis mit allen Notizen öffnen", run: () => openMemory() },
  { name: "workspace", description: "Workspace wählen", run: () => openWorkspace() },
  { name: "models", description: "Modell wählen und laden", run: () => openModels() },
  { name: "settings", description: "Einstellungen", run: () => openSettings() },
];
const COMMAND_ALIASES = { clear: "new", model: "models" };

function expandCommand(cmd, args) {
  const words = args ? args.split(/\s+/) : [];
  let text = cmd.template.replace(/\$ARGUMENTS/g, args).replace(/\$(\d)/g, (_, n) => words[n - 1] ?? "");
  if (args && !/\$ARGUMENTS|\$\d/.test(cmd.template)) text += `\n\n${args}`;
  return text;
}

function clearInput() {
  input.value = "";
  autosize();
  updateSendState();
}

async function submit() {
  if (state.busy) {
    send({ type: "cancel" });
    return;
  }
  if (attachments.some((a) => a.pending)) {
    toast("Das Bild wird noch vorbereitet …");
    return;
  }
  const images = attachments.filter((a) => a.id).map((a) => a.id);
  const text = input.value.trim() || (images.length ? "Was ist auf dem Bild zu sehen?" : "");
  if (!text) return;
  hideSuggest();
  let prompt = text;
  if (text.startsWith("/")) {
    const head = text.split(/\s+/)[0];
    const name = head.slice(1).toLowerCase();
    const builtin = BUILTIN_COMMANDS.find((c) => c.name === (COMMAND_ALIASES[name] || name));
    if (builtin) {
      clearInput();
      builtin.run();
      return;
    }
    const custom = (await loadExtensions().catch(() => null))?.commands.find((c) => c.name === name);
    if (custom) prompt = expandCommand(custom, text.slice(head.length).trim());
  }
  if (state.ollama && !state.ollama.ok) {
    toast("Ollama ist nicht erreichbar. Starte Ollama und versuche es erneut.", { error: true });
    return;
  }
  addUser(text, images);
  scrollDown(true);
  state.runAgent = null;
  state.runLabeled = false;
  send({ type: "send", text: prompt, ...(prompt === text ? {} : { display: text }), ...(images.length ? { images } : {}) });
  setBusy(true);
  setActivity(liveModel() ? "Denkt nach …" : "Modell wird vorbereitet …");
  attachments.length = 0;
  renderAttachments();
  clearInput();
}

$("#composer").addEventListener("submit", (e) => { e.preventDefault(); submit(); });
input.addEventListener("input", () => { autosize(); updateSendState(); updateSuggest(); });
input.addEventListener("keydown", (e) => {
  if (!$("#suggest").hidden && !e.isComposing) {
    const n = suggest.items.length;
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && n) {
      e.preventDefault();
      suggest.index = (suggest.index + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
      renderSuggest();
      return;
    }
    if ((e.key === "Enter" || e.key === "Tab") && n && !e.shiftKey) {
      e.preventDefault();
      pickSuggest();
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // sonst würde Esc den laufenden Agent stoppen
      hideSuggest();
      return;
    }
  }
  if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;
  if (e.ctrlKey || e.metaKey) return; // Strg+Enter gehört der Freigabe
  e.preventDefault();
  if (state.busy) queueMessage(); // während der Arbeit: für den nächsten Schritt einreihen
  else submit();
});
$("#suggestions").addEventListener("click", (e) => {
  const row = e.target.closest("[data-prompt]");
  if (!row) return;
  input.value = row.dataset.prompt;
  autosize();
  updateSendState();
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
});

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = Object.assign(document.createElement("textarea"), { value: text });
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
}

document.addEventListener("click", async (e) => {
  const copy = e.target.closest("[data-copy], [data-copy-answer]");
  if (!copy) return;
  const answer = copy.hasAttribute("data-copy-answer");
  await copyText(answer ? copy.closest(".turn.agent")?.raw || "" : copy.closest(".code").querySelector("pre").textContent);
  const label = answer ? copy : $("span", copy);
  label.textContent = "Kopiert";
  setTimeout(() => (label.textContent = "Kopieren"), 1400);
});

/* ================================================================ @Agents und /Befehle */

const suggest = { kind: null, items: [], index: 0, start: 0, seq: 0 };

async function loadExtensions(force = false) {
  const ws = currentWorkspace();
  if (!force && state.ext?.ws === ws) return state.ext;
  const q = `?workspace=${encodeURIComponent(ws)}`;
  const [a, c] = await Promise.all([api(`/api/agents${q}`), api(`/api/commands${q}`)]);
  state.ext = { ws, agents: a.agents, tools: a.tools, commands: c.commands };
  return state.ext;
}

function suggestContext() {
  const caret = input.selectionStart;
  if (caret !== input.selectionEnd) return null;
  const before = input.value.slice(0, caret);
  let m = before.match(/\[\[([^[\]\n]*)$/);
  if (m) return { kind: "note", query: m[1].toLowerCase(), start: caret - m[1].length - 2 };
  m = before.match(/(^|\s)@([\w-]*)$/);
  if (m) return { kind: "agent", query: m[2].toLowerCase(), start: caret - m[2].length - 1 };
  m = before.match(/^\/([\w:-]*)$/);
  if (m) return { kind: "command", query: m[1].toLowerCase(), start: 0 };
  return null;
}

async function updateSuggest() {
  const ctx = suggestContext();
  if (!ctx) return hideSuggest();
  const seq = ++suggest.seq;
  let source;
  try {
    source = ctx.kind === "note" ? await loadNotes() : await loadExtensions();
  } catch {
    return hideSuggest();
  }
  if (seq !== suggest.seq) return;
  const rank = (a) => Object.keys(SOURCE_LABEL).indexOf(a.source); // eigene Agents vor den eingebauten
  let items;
  if (ctx.kind === "note") {
    items = source.notes.map((n) => ({ name: n.title, description: n.excerpt || n.tags.map((t) => `#${t}`).join(" "),
      hint: n.vault === "project" ? "" : vaultLabel(n.vault), icon: ICONS.note, prefix: "" }));
  } else if (ctx.kind === "agent") {
    items = [...source.agents].sort((x, y) => rank(x) - rank(y)).map((a) => ({ ...a, icon: ICONS.agent, prefix: "@" }));
  } else {
    items = [...BUILTIN_COMMANDS, ...source.commands].map((c) => ({ ...c, icon: ICONS.command, prefix: "/" }));
  }
  const lower = (it) => it.name.toLowerCase();
  const fits = (it) => !ctx.query || lower(it).includes(ctx.query) || (it.description || "").toLowerCase().includes(ctx.query);
  const found = items.filter(fits).sort((x, y) => lower(y).startsWith(ctx.query) - lower(x).startsWith(ctx.query));
  Object.assign(suggest, { kind: ctx.kind, items: found.slice(0, 50), index: 0, start: ctx.start });
  renderSuggest();
}

function renderSuggest() {
  const box = $("#suggest");
  const rows = suggest.items.map((it, i) => `
    <button type="button" class="suggest-item" role="option" data-i="${i}" aria-selected="${i === suggest.index}">
      <span class="suggest-icon">${it.icon}</span>
      <span class="suggest-name${suggest.kind === "note" ? " plain" : ""}">${it.prefix}${esc(it.name)}${it.hint ? ` <span class="suggest-hint">${esc(it.hint)}</span>` : ""}</span>
      <span class="suggest-desc">${esc(it.description)}</span>
    </button>`).join("");
  box.innerHTML = `<div class="suggest-head eyebrow">${{ agent: "Agents", command: "Befehle", note: "Notizen" }[suggest.kind]}</div>` +
    (rows || `<div class="suggest-empty">Nichts gefunden.</div>`);
  box.hidden = false;
  $(`[data-i="${suggest.index}"]`, box)?.scrollIntoView({ block: "nearest" });
}

function hideSuggest() {
  suggest.seq++;
  suggest.kind = null;
  $("#suggest").hidden = true;
}

function pickSuggest(i = suggest.index) {
  const item = suggest.items[i];
  if (!item) return hideSuggest();
  if (suggest.kind === "note") {
    const token = `[[${item.name}]] `;
    input.value = input.value.slice(0, suggest.start) + token + input.value.slice(input.selectionStart).replace(/^\]{0,2}\s?/, "");
    input.setSelectionRange(suggest.start + token.length, suggest.start + token.length);
  } else if (suggest.kind === "agent") {
    const token = `@${item.name} `;
    input.value = input.value.slice(0, suggest.start) + token + input.value.slice(input.selectionStart).replace(/^\s+/, "");
    input.setSelectionRange(suggest.start + token.length, suggest.start + token.length);
  } else if (item.run) {
    hideSuggest();
    clearInput();
    item.run();
    return;
  } else {
    input.value = `/${item.name} `;
  }
  hideSuggest();
  autosize();
  updateSendState();
  input.focus();
}

$("#suggest").addEventListener("mousedown", (e) => e.preventDefault()); // Fokus bleibt in der Eingabe
$("#suggest").addEventListener("click", (e) => {
  const row = e.target.closest("[data-i]");
  if (row) pickSuggest(Number(row.dataset.i));
});
input.addEventListener("blur", () => setTimeout(() => { if (document.activeElement !== input) hideSuggest(); }, 150));

function updatePlaceholder() {
  const narrow = matchMedia("(max-width: 560px)").matches;
  if (state.busy) input.placeholder = narrow ? "Nachricht an den Agent" : "Weitere Nachricht – der Agent liest sie vor seinem nächsten Schritt";
  else input.placeholder = narrow ? "Aufgabe, @Agent oder /Befehl" : "Beschreibe eine Aufgabe – @ für Agents, / für Befehle";
}
window.addEventListener("resize", updatePlaceholder);

// [[Links]] im Chat und in Notizen öffnen die Notiz im Gedächtnis
document.addEventListener("click", (e) => {
  const link = e.target.closest(".wikilink");
  if (!link) return;
  e.preventDefault();
  const sheet = $("#memorySheet");
  if (!sheet.hidden && !sheet.classList.contains("closing")) {
    setMemoryView("notes");
    showNote(link.dataset.note);
  } else {
    openMemory({ title: link.dataset.note });
  }
});

// Hineingezogene Dateien würden die App verlassen und die Datei öffnen – Bilder landen stattdessen in der Eingabe.
let dragDepth = 0;
const draggingFiles = (e) => !!e.dataTransfer?.types?.includes("Files");
document.addEventListener("dragenter", (e) => {
  if (!draggingFiles(e)) return;
  dragDepth++;
  $("#composer").classList.add("dropping");
});
document.addEventListener("dragleave", (e) => {
  if (!draggingFiles(e)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $("#composer").classList.remove("dropping");
});
document.addEventListener("dragover", (e) => { if (draggingFiles(e)) e.preventDefault(); });
document.addEventListener("drop", (e) => {
  if (!draggingFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("#composer").classList.remove("dropping");
  addImages(e.dataTransfer.files).then((added) => { if (!added) toast("Anhängen lassen sich nur Bilder."); });
});

/* ================================================================ Sheets */

let sheetReturnFocus = null;
function openSheet(id) {
  const el = $(id);
  clearTimeout(el.closeTimer); // schließt es gerade, bleibt es einfach offen
  el.classList.remove("closing");
  sheetReturnFocus = document.activeElement;
  el.hidden = false;
  // Fokus in den Dialog, damit Tab nicht hinter dem Schleier landet – ohne einen Knopf hervorzuheben.
  const sheet = $(".sheet", el);
  sheet.tabIndex = -1;
  sheet.focus({ preventScroll: true });
  return el;
}
function closeSheets() {
  const open = $$(".sheet-backdrop:not([hidden]):not(.closing)");
  for (const backdrop of open) {
    backdrop.classList.add("closing"); // erst ausblenden, dann entfernen
    backdrop.closeTimer = setTimeout(() => {
      backdrop.hidden = true;
      backdrop.classList.remove("closing");
    }, 240);
  }
  if (open.length) sheetReturnFocus?.focus?.();
}
$$(".sheet-backdrop").forEach((bd) => {
  bd.addEventListener("mousedown", (e) => { if (e.target === bd) closeSheets(); });
  $$("[data-close]", bd).forEach((b) => b.addEventListener("click", closeSheets));
});

async function openModels() {
  openSheet("#modelSheet");
  $("#hwStats").innerHTML = Array(3).fill(`<div class="stat"><div class="eyebrow">&nbsp;</div><div class="stat-skeleton"></div></div>`).join("");
  $("#modelList").innerHTML = `<div class="model-empty"><span class="spinner"></span></div>`;
  $("#envTips").innerHTML = "";
  try {
    renderModels(await api("/api/models"));
  } catch (e) {
    $("#hwStats").innerHTML = "";
    $("#modelList").innerHTML = `<div class="model-empty">${esc(e.message)}<br><br><button class="btn" type="button" id="retryModels">Erneut versuchen</button></div>`;
    $("#retryModels").addEventListener("click", openModels);
  }
}

function renderStats(hw) {
  const gpu = hw.gpus[0];
  const tiles = [
    ["Grafikkarte", gpu ? gpu.name.replace(/^NVIDIA (GeForce )?/, "") : "Keine", gpu ? `${gb(hw.vram_total)} VRAM` : "läuft auf der CPU"],
    ["VRAM frei", gpu ? gb(hw.vram_free) : "–", gpu ? `von ${gb(hw.vram_total)}` : ""],
    ["System", `${gb(hw.ram_total)} RAM`, `${hw.cores} Kerne · ${hw.os}`],
  ];
  $("#hwStats").innerHTML = tiles.map(([label, value, sub]) =>
    `<div class="stat"><div class="eyebrow">${esc(label)}</div><div class="stat-value" title="${esc(value)}">${esc(value)}</div><div class="stat-sub">${esc(sub)}</div></div>`).join("");
}

function renderModels(data) {
  renderStats(data.hardware);
  const list = $("#modelList");
  if (!data.models.length) {
    list.innerHTML = `<div class="model-empty">Noch keine Modelle installiert.<br><br><code>ollama pull qwen3-coder:30b</code></div>`;
    return;
  }
  const body = list.closest(".sheet-body");
  const scrollTop = body.scrollTop;
  list.innerHTML = "";
  for (const m of data.models) {
    const p = m.profile;
    const plan = m.plan;
    const current = m.name === state.config.model;
    const share = m.loaded ? m.loaded.gpu_share : plan.gpu_share;
    const ctx = m.loaded?.context_length || plan.num_ctx;
    const caps = p.capabilities;
    const badges = [
      m.name === data.recommended ? `<span class="badge rec">Empfohlen</span>` : "",
      m.loaded ? `<span class="badge live">Geladen</span>` : "",
      caps.includes("tools") ? `<span class="badge">Tools</span>` : "",
      caps.includes("thinking") ? `<span class="badge">Denken</span>` : "",
      caps.includes("vision") ? `<span class="badge">Vision</span>` : "",
    ].join("");
    const sub = [p.params, p.quant, gb(p.size), p.moe ? "MoE" : "", `bis ${kctx(p.ctx_max)} Kontext`].filter(Boolean).join(" · ");
    const fitText = m.loaded
      ? `Gemessen: ${pct(share)} auf der GPU · ${kctx(ctx)} Kontext`
      : `${share >= 0.999 ? "Passt komplett in die GPU" : `Etwa ${pct(share)} auf der GPU`} · ${kctx(ctx)} Kontext · ~${gb(plan.estimate_bytes)}`;
    const useClass = !current && m.name === data.recommended ? "btn primary" : "btn";

    const el = document.createElement("div");
    el.className = `model${current ? " current" : ""}`;
    el.innerHTML = `
      <div>
        <div class="model-title">${esc(m.name)} ${badges}</div>
        <div class="model-sub">${esc(sub)}</div>
      </div>
      <div class="model-actions">
        ${m.loaded ? `<button class="btn ghost" type="button" data-unload>Entladen</button>` : ""}
        <button class="${useClass}" type="button" data-load>${current && m.loaded ? "Neu laden" : "Verwenden"}</button>
      </div>
      <div class="fit">
        <span>${fitText}</span>
        <div class="fit-bar" role="img" aria-label="${pct(share)} auf der GPU"><i class="${share >= 0.999 ? "" : "part"}" style="width:${Math.max(3, share * 100)}%"></i></div>
      </div>`;
    $("[data-load]", el).addEventListener("click", (e) => loadModel(m.name, e.currentTarget));
    $("[data-unload]", el)?.addEventListener("click", (e) => unloadModel(m.name, e.currentTarget));
    list.append(el);
  }
  renderTips(data);
  body.scrollTop = scrollTop; // nach „Verwenden“ nicht an den Anfang der Liste springen
}

function renderTips(data) {
  const current = data.models.find((m) => m.name === state.config.model) || data.models.find((m) => m.name === data.recommended);
  const notes = current ? current.plan.notes.filter((n) => !n.startsWith("OLLAMA_")) : [];
  const env = data.env || {};
  const win = data.hardware.os === "Windows";
  const wanted = { OLLAMA_FLASH_ATTENTION: "1", OLLAMA_KV_CACHE_TYPE: "q8_0", OLLAMA_NUM_PARALLEL: "1" };
  const missing = Object.entries(wanted).filter(([k, v]) => String(env[k] || "").toLowerCase() !== v);
  let html = "";
  if (notes.length) html += `<h3>${esc(current.name)}</h3><ul>${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`;
  if (missing.length) {
    const cmds = missing.map(([k, v]) => (win ? `setx ${k} ${v}` : `export ${k}=${v}`));
    html += `<h3>Mehr Kontext bei gleichem VRAM</h3><ul>${cmds.map((c) => `<li><code>${esc(c)}</code></li>`).join("")}` +
      `<li>Danach Ollama neu starten. Der KV-Cache halbiert sich damit.</li></ul>`;
  }
  $("#envTips").innerHTML = html;
}

async function loadModel(name, btn) {
  state.modelLoading = true;
  $$("#modelList .btn").forEach((b) => (b.disabled = true));
  const width = btn.offsetWidth;
  btn.style.width = `${width}px`;
  btn.innerHTML = `<span class="spinner"></span>`;
  setModelDot("busy");
  $("#modelName").textContent = name;
  $("#modelMeta").textContent = "wird geladen …";
  try {
    const res = await api("/api/models/load", { method: "POST", body: { model: name } });
    state.config.model = name;
    state.plan = res.plan;
    state.loaded = res.loaded;
    const a = res.plan.actual;
    toast(`${name} ist bereit · ${pct(a ? a.gpu_share : res.plan.gpu_share)} GPU · ${kctx(res.plan.num_ctx)} Kontext · ${nf.format(res.plan.load_seconds)} s`);
    updateModelPill();
    updateStart();
    renderModels(await api("/api/models"));
  } catch (e) {
    toast(e.message, { error: true, ms: 5000 });
    updateModelPill();
    $$("#modelList .btn").forEach((b) => (b.disabled = false));
    btn.style.width = "";
    btn.textContent = "Verwenden";
  } finally {
    state.modelLoading = false;
  }
}

async function unloadModel(name, btn) {
  btn.disabled = true;
  try {
    const res = await api("/api/models/unload", { method: "POST", body: { model: name } });
    state.loaded = res.loaded;
    updateModelPill();
    updateStart();
    renderModels(await api("/api/models"));
  } catch (e) {
    toast(e.message, { error: true });
    btn.disabled = false;
  }
}

function openSettings() {
  const form = $("#settingsForm");
  const c = state.config;
  for (const el of form.elements) {
    if (!el.name || !(el.name in c)) continue;
    if (el.type === "checkbox") el.checked = !!c[el.name];
    // Coder 1.2 speicherte „PC wach halten“ als an/aus – sonst bliebe die Auswahl leer und würde leer gesichert.
    else if (el.name === "keep_awake" && typeof c.keep_awake === "boolean") el.value = c.keep_awake ? "open" : "off";
    else el.value = String(c[el.name] ?? "");
  }
  openSheet("#settingsSheet");
  loadModelOptions();
}

// Kontroll- und Bildmodell: Auswahl aus den installierten Modellen. „Automatisch“ nennt, wen Coder nehmen würde.
async function loadModelOptions() {
  let data;
  try {
    data = state.models && Date.now() - state.models.at < 60000 ? state.models.data : await api("/api/models");
    state.models = { at: Date.now(), data };
  } catch {
    return;
  }
  const roles = data.roles || {};
  for (const select of $$("#settingsForm select[data-models]")) {
    const vision = select.dataset.models === "vision";
    const names = data.models.filter((m) => !vision || m.profile.capabilities.includes("vision")).map((m) => m.name);
    const auto = vision ? roles.vision : roles.controller;
    const current = String(state.config[select.name] || "");
    if (current && !names.includes(current)) names.unshift(current);
    select.innerHTML = `<option value="">${esc(auto ? `Automatisch · ${auto}` : "Automatisch")}</option>`
      + names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
    select.value = current;
  }
}

$("#settingsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  const changes = {};
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") changes[el.name] = el.checked;
    else if (el.name === "temperature") changes[el.name] = el.value === "" ? null : Number(el.value);
    else if (["num_ctx", "max_auto_ctx", "max_steps", "command_timeout", "controller_rounds", "controller_interval", "watchdog"].includes(el.name)) {
      changes[el.name] = Number(el.value);
    }
    else changes[el.name] = el.value.trim();
  }
  const submitBtn = $("button[type=submit]", form);
  submitBtn.disabled = true;
  try {
    state.config = await api("/api/config", { method: "POST", body: changes });
    state.ext = null; // Claude-Code-Erweiterungen können an- oder abgeschaltet worden sein
    memoryUI.data = null;
    closeSheets();
    toast("Gesichert");
    loadState();
  } catch (err) {
    toast(err.message, { error: true, ms: 4500 });
  } finally {
    submitBtn.disabled = false;
  }
});

/* ================================================================ Workspace */

const picker = { seq: 0, timer: null };
const ROW_ARROW = ICONS.chevron.replace("<svg", '<svg class="row-arrow"');

function openWorkspace() {
  if (state.busy) return toast("Der Agent arbeitet noch – erst stoppen, dann den Ordner wechseln.");
  openSheet("#workspaceSheet");
  const field = $("#wsPath");
  field.value = currentWorkspace();
  $("#wsNative").hidden = !state.nativePicker;
  setPickerStatus("");
  browseFolder(field.value, true);
  field.focus();
  field.select();
  api("/api/folders/places").then(renderPlaces).catch(() => { /* Abkürzungen sind optional */ });
}

function setPickerStatus(text, error = false) {
  const el = $("#wsStatus");
  el.textContent = text;
  el.classList.toggle("error", error);
}

async function browseFolder(path, keepField = false) {
  const seq = ++picker.seq;
  let data;
  try {
    data = await api(`/api/folders?path=${encodeURIComponent(path)}`);
  } catch (e) {
    if (seq === picker.seq) setPickerStatus(e.message, true);
    return;
  }
  if (seq !== picker.seq) return;
  if (!keepField) $("#wsPath").value = data.path;
  const problem = data.error || (data.blocked ? `Geht nicht als Workspace: ${data.blocked}` : "");
  setPickerStatus(problem, !!problem);
  $("#wsUse").disabled = !!problem;
  if (!data.dirs) return; // Pfad ungültig: die letzte Liste bleibt stehen
  const rows = [];
  if (data.parent) {
    rows.push(`<button type="button" class="list-row" data-browse="${esc(data.parent)}">
      <span class="row-icon">${ICONS.up}</span>
      <span class="row-text"><strong>Übergeordneter Ordner</strong><span class="path">${esc(ltr(data.parent))}</span></span>
    </button>`);
  }
  for (const d of data.dirs) {
    rows.push(`<button type="button" class="list-row" data-browse="${esc(d.path)}">
      <span class="row-icon">${ICONS.folder}</span>
      <span class="row-text"><strong>${esc(d.name)}</strong></span>${ROW_ARROW}
    </button>`);
  }
  if (!data.dirs.length) rows.push(`<div class="ws-empty">Keine Unterordner</div>`);
  const list = $("#wsBrowser");
  list.innerHTML = rows.join("");
  list.scrollTop = 0;
}

function renderPlaces({ places = [], recent = [] }) {
  const current = currentWorkspace().toLowerCase();
  $("#wsRecentBlock").hidden = !recent.length;
  $("#wsRecent").innerHTML = recent.map((r) => `
    <button type="button" class="list-row" data-apply="${esc(r.path)}">
      <span class="row-icon">${ICONS.folder}</span>
      <span class="row-text"><strong>${esc(r.name)}</strong><span class="path">${esc(ltr(r.path))}</span></span>
      ${r.path.toLowerCase() === current ? `<span class="row-check" title="Aktueller Workspace">${ICONS.check}</span>` : ROW_ARROW}
    </button>`).join("");
  $("#wsPlaces").innerHTML = places.map((p) =>
    `<button type="button" class="chip" data-browse="${esc(p.path)}" title="${esc(p.path)}"><span>${esc(p.name)}</span></button>`).join("");
}

async function applyWorkspace(path) {
  const btn = $("#wsUse");
  btn.disabled = true;
  try {
    state.config = await api("/api/config", { method: "POST", body: { workspace: path } });
    closeSheets();
    // Ein Chat bleibt an seinen Ordner gebunden – ein anderer Ordner heißt: neuer Chat.
    if (state.session?.workspace !== state.config.workspace) send({ type: "new" });
    updateWorkspace();
    toast(`Workspace: ${basename(state.config.workspace)}`);
    input.focus();
  } catch (e) {
    setPickerStatus(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function pickNative() {
  const btn = $("#wsNative");
  btn.disabled = true;
  try {
    const { path } = await api("/api/folders/pick", { method: "POST", body: { start: $("#wsPath").value } });
    if (path) {
      $("#wsPath").value = path;
      await applyWorkspace(path);
    }
  } catch (e) {
    setPickerStatus(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

$("#wsForm").addEventListener("submit", (e) => {
  e.preventDefault();
  applyWorkspace($("#wsPath").value);
});
$("#wsForm").addEventListener("click", (e) => {
  const row = e.target.closest("[data-browse], [data-apply]");
  if (!row) return;
  if (row.dataset.apply) applyWorkspace(row.dataset.apply);
  else browseFolder(row.dataset.browse);
});
$("#wsPath").addEventListener("input", (e) => {
  clearTimeout(picker.timer);
  picker.timer = setTimeout(() => browseFolder(e.target.value, true), 250);
});
$("#wsNative").addEventListener("click", pickNative);

/* ================================================================ Gedächtnis */

const memoryUI = { data: null, ws: null, current: null, note: null, query: "", tag: null, view: "notes" };
const vaultLabel = (vault) => ({ project: "Projekt", global: "Global", library: "Bibliothek", missing: "Noch nicht angelegt" }[vault] || vault);

async function loadNotes(force = false) {
  const ws = currentWorkspace();
  if (!force && memoryUI.data && memoryUI.ws === ws) return memoryUI.data;
  memoryUI.data = await api(`/api/memory?workspace=${encodeURIComponent(ws)}`);
  memoryUI.ws = ws;
  return memoryUI.data;
}

function sinceLabel(ts) {
  const seconds = Date.now() / 1000 - ts;
  if (seconds < 60) return "gerade eben";
  if (seconds < 3600) return `vor ${Math.floor(seconds / 60)} Min.`;
  if (seconds < 86400) return `vor ${Math.floor(seconds / 3600)} Std.`;
  return whenLabel(ts);
}

async function openMemory(target = null) {
  const sheet = $("#memorySheet");
  if (sheet.hidden || sheet.classList.contains("closing")) openSheet("#memorySheet");
  setMemoryView("notes");
  try {
    await loadNotes(true);
  } catch (e) {
    $("#noteView").innerHTML = `<div class="note-empty"><p>${esc(e.message)}</p></div>`;
    return;
  }
  renderNoteList();
  const notes = memoryUI.data.notes;
  const remembered = notes.find((n) => n.id === memoryUI.current);
  if (target?.title) showNote(target.title, target.vault);
  else if (remembered) showNote(remembered.title, remembered.vault);
  else if (notes.length && !matchMedia("(max-width: 760px)").matches) showNote(notes[0].title, notes[0].vault);
  else renderNoteEmpty();
}

function noteRow(n) {
  const links = n.links.length + (n.backlinks || 0);
  const meta = [vaultLabel(n.vault), links ? `${links} ${links === 1 ? "Verbindung" : "Verbindungen"}` : "", sinceLabel(n.updated)]
    .filter(Boolean).join(" · ");
  return `<button type="button" class="note-row" data-note="${esc(n.title)}" data-vault="${n.vault}" aria-current="${memoryUI.current === n.id}">
    <span class="note-row-title">${n.pinned ? ICONS.pin : ""}<span>${esc(n.title)}</span></span>
    <span class="note-row-excerpt">${esc(n.excerpt)}</span>
    <span class="note-row-meta">${esc(meta)}</span>
  </button>`;
}

function renderNoteList() {
  const { notes, tags } = memoryUI.data;
  const query = memoryUI.query.toLowerCase();
  $("#noteTags").innerHTML = Object.entries(tags).slice(0, 14).map(([tag, count]) =>
    `<button type="button" class="tag-chip" data-tag="${esc(tag)}" aria-pressed="${memoryUI.tag === tag}" title="${count} ${count === 1 ? "Notiz" : "Notizen"}">#${esc(tag)}</button>`).join("");
  const visible = notes.filter((n) => (!memoryUI.tag || n.tags.includes(memoryUI.tag))
    && (!query || `${n.title} ${n.excerpt} ${n.tags.join(" ")}`.toLowerCase().includes(query)));
  const groups = [
    ["Angeheftet", visible.filter((n) => n.pinned)],
    ["Projekt", visible.filter((n) => !n.pinned && n.vault === "project")],
    ["Global", visible.filter((n) => !n.pinned && n.vault === "global")],
    ["Bibliothek", visible.filter((n) => !n.pinned && n.vault === "library")],
  ].filter(([, list]) => list.length);
  $("#noteList").innerHTML = groups.map(([label, list]) => `<span class="note-group eyebrow">${label}</span>${list.map(noteRow).join("")}`).join("")
    || `<div class="note-list-empty">${notes.length ? "Keine passenden Notizen." : "Noch keine Notizen."}</div>`;
}

async function showNote(title, vault) {
  const query = new URLSearchParams({ title, workspace: currentWorkspace() });
  if (vault && vault !== "missing") query.set("vault", vault);
  let note;
  try {
    note = await api(`/api/memory/note?${query}`);
  } catch {
    return editNote({ title, content: "", vault: "project", pinned: false, isNew: true }); // Link ins Leere: Notiz anlegen
  }
  memoryUI.current = note.id;
  memoryUI.note = note;
  $("#memoryBody").classList.add("reading");
  $$("#noteList .note-row").forEach((row) => row.setAttribute("aria-current", String(`${row.dataset.vault}:${row.dataset.note}` === note.id)));
  const tags = note.tags.map((t) => `<button type="button" class="tag-chip" data-tag="${esc(t)}">#${esc(t)}</button>`).join("");
  const backlinks = note.backlinks.length
    ? `<section class="note-backlinks"><span class="eyebrow">Verlinkt von</span><div class="list">${note.backlinks.map(noteRow).join("")}</div></section>`
    : "";
  $("#noteView").innerHTML = `
    <article class="note-read">
      <button type="button" class="btn ghost note-back" data-back>${ICONS.back}Notizen</button>
      <div class="note-meta"><span class="badge${note.vault === "library" ? " library" : ""}">${vaultLabel(note.vault)}</span>${note.pinned ? `<span class="badge rec">Angeheftet</span>` : ""}<span>${note.vault === "library" ? "Schreibgeschützt · kommt mit Coder" : `Geändert ${sinceLabel(note.updated)}`}</span></div>
      <h1 class="note-title">${esc(note.title)}</h1>
      <div class="note-tags">${tags}</div>
      <div class="md note-md">${markdown(note.content) || "<p>Diese Notiz ist noch leer.</p>"}</div>
      ${backlinks}
      <div class="note-actions">${note.vault === "library"
        ? `<button type="button" class="btn" data-note-copy>In mein Gedächtnis kopieren</button>`
        : `<button type="button" class="btn" data-note-edit>Bearbeiten</button>
        <button type="button" class="btn ghost" data-note-pin>${note.pinned ? "Lösen" : "Anheften"}</button>
        <span class="spacer"></span>
        <button type="button" class="btn ghost danger" data-note-delete>Löschen</button>`}
      </div>
    </article>`;
  // Links auf Notizen, die es noch nicht gibt, sind gestrichelt – ein Klick legt sie an
  const resolved = Object.fromEntries(Object.entries(note.resolved).map(([k, v]) => [k.toLowerCase(), v]));
  $$("#noteView .note-md .wikilink").forEach((a) => a.classList.toggle("missing", !resolved[a.dataset.note.toLowerCase()]));
  $("#noteView").scrollTop = 0;
}

function renderNoteEmpty() {
  memoryUI.current = null;
  $("#memoryBody").classList.remove("reading");
  const empty = !memoryUI.data?.notes.length;
  $("#noteView").innerHTML = `
    <div class="note-empty">${ICONS.graph}
      <strong>${empty ? "Noch keine Notizen" : "Wähle eine Notiz"}</strong>
      <p>${empty ? "Coder legt Notizen an, sobald er etwas Dauerhaftes lernt: Vorlieben, Entscheidungen, Lösungen. Oder du beginnst selbst."
        : "Links in einer Notiz führen direkt zur nächsten."}</p>
      ${empty ? `<button type="button" class="btn primary" data-note-create>Erste Notiz anlegen</button>` : ""}
    </div>`;
}

function editNote(note) {
  const isNew = !note || note.isNew;
  const n = note || { title: "", content: "", vault: "project", pinned: false };
  $("#memoryBody").classList.add("reading");
  $("#noteView").innerHTML = `
    <form class="note-edit" id="noteForm" autocomplete="off">
      <input class="note-title-input" name="title" value="${esc(n.title)}" placeholder="Titel der Notiz" maxlength="120" spellcheck="false">
      <div class="note-edit-bar">
        <div class="view-switch" role="radiogroup" aria-label="Tresor">
          <button type="button" role="radio" data-vault="project" aria-checked="${n.vault !== "global"}">Projekt</button>
          <button type="button" role="radio" data-vault="global" aria-checked="${n.vault === "global"}">Global</button>
        </div>
        <label><input type="checkbox" class="switch" name="pinned"${n.pinned ? " checked" : ""}>Angeheftet</label>
      </div>
      <textarea class="note-textarea" name="content" spellcheck="false" placeholder="Markdown. Verknüpfe mit [[Titel]], ordne mit #tags.">${esc(n.content || "")}</textarea>
      <p class="form-error" id="noteError" role="alert"></p>
      <div class="sheet-actions">
        <button type="button" class="btn ghost" data-note-cancel>Abbrechen</button>
        <button type="submit" class="btn primary">Sichern</button>
      </div>
    </form>`;
  const form = $("#noteForm");
  form.dataset.original = isNew ? "" : n.title;
  form.dataset.originalVault = isNew ? "" : n.vault;
  (n.title ? form.elements.content : form.elements.title).focus();
}

async function saveNote(form) {
  const body = {
    workspace: currentWorkspace(),
    title: form.elements.title.value,
    content: form.elements.content.value,
    vault: $("[data-vault][aria-checked=true]", form)?.dataset.vault || "project",
    pinned: form.elements.pinned.checked,
  };
  if (form.dataset.original) Object.assign(body, { original_title: form.dataset.original, original_vault: form.dataset.originalVault });
  const btn = $("button[type=submit]", form);
  btn.disabled = true;
  try {
    const note = await api("/api/memory/note", { method: "POST", body });
    await loadNotes(true);
    renderNoteList();
    showNote(note.title, note.vault);
    toast(`„${note.title}“ gesichert`);
  } catch (e) {
    $("#noteError").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

// Leitfäden der Bibliothek sind schreibgeschützt – eine Kopie im globalen Gedächtnis lässt sich anpassen.
async function copyNote(note) {
  try {
    const body = { workspace: currentWorkspace(), title: note.title, content: note.content, vault: "global" };
    const saved = await api("/api/memory/note", { method: "POST", body });
    await loadNotes(true);
    renderNoteList();
    editNote(saved);
    toast(`„${saved.title}“ liegt jetzt in deinem globalen Gedächtnis`);
  } catch (e) {
    toast(e.message, { error: true });
  }
}

async function togglePin(note) {
  try {
    const body = { workspace: currentWorkspace(), title: note.title, vault: note.vault, content: note.content, pinned: !note.pinned };
    const saved = await api("/api/memory/note", { method: "POST", body });
    await loadNotes(true);
    renderNoteList();
    showNote(saved.title, saved.vault);
  } catch (e) {
    toast(e.message, { error: true });
  }
}

async function deleteNote(note) {
  if (!confirm(`„${note.title}“ löschen?`)) return;
  try {
    const query = new URLSearchParams({ title: note.title, vault: note.vault, workspace: currentWorkspace() });
    await api(`/api/memory/note?${query}`, { method: "DELETE" });
    await loadNotes(true);
    renderNoteList();
    renderNoteEmpty();
    toast(`„${note.title}“ gelöscht`);
  } catch (e) {
    toast(e.message, { error: true });
  }
}

function setMemoryView(view) {
  memoryUI.view = view;
  $$("#memorySheet .sheet-head .view-switch button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === view)));
  $("#memoryBody").classList.toggle("graph-mode", view === "graph");
  $("#noteGraph").hidden = view !== "graph";
  $("#noteNew").hidden = view === "graph";
  if (view === "graph") renderGraph();
}

/* Kräftebasiertes Layout (Fruchterman-Reingold): verknüpfte Notizen ziehen sich an, alle anderen stoßen sich ab. */
function layoutGraph(nodes, links, width, height) {
  const n = nodes.length;
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const edges = links.map((l) => [index.get(l.source), index.get(l.target)])
    .filter(([a, b]) => a !== undefined && b !== undefined && a !== b);
  const k = Math.max(40, Math.sqrt((width * height) / Math.max(n, 1)) * 0.6);
  // Start auf einer Spirale statt zufällig: der Graph sieht bei jedem Öffnen gleich aus
  const pos = nodes.map((_, i) => [Math.cos(i * 2.4) * k * 0.5 * Math.sqrt(i + 1), Math.sin(i * 2.4) * k * 0.5 * Math.sqrt(i + 1)]);
  let temperature = k * 2;
  const reach = (k * 3) ** 2;
  for (let step = 0; step < 280; step++) {
    const disp = pos.map(() => [0, 0]);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = pos[i][0] - pos[j][0];
        const dy = pos[i][1] - pos[j][1];
        const d2 = dx * dx + dy * dy;
        // Nur Nachbarn stoßen sich ab: Sonst treibt ein dichter Cluster lose Notizen an den Rand,
        // und das Einpassen ins Fenster quetscht alles zusammen.
        if (d2 > reach) continue;
        const f = (k * k) / Math.max(d2, 1);
        disp[i][0] += dx * f; disp[i][1] += dy * f;
        disp[j][0] -= dx * f; disp[j][1] -= dy * f;
      }
    }
    for (const [a, b] of edges) {
      const dx = pos[a][0] - pos[b][0];
      const dy = pos[a][1] - pos[b][1];
      const f = Math.hypot(dx, dy) / k;
      disp[a][0] -= dx * f; disp[a][1] -= dy * f;
      disp[b][0] += dx * f; disp[b][1] += dy * f;
    }
    for (let i = 0; i < n; i++) {
      disp[i][0] -= pos[i][0] * 0.05; // sanfte Schwerkraft hält lose Notizen im Bild
      disp[i][1] -= pos[i][1] * 0.05;
      const len = Math.hypot(disp[i][0], disp[i][1]) || 1;
      const move = Math.min(len, temperature);
      pos[i][0] += (disp[i][0] / len) * move;
      pos[i][1] += (disp[i][1] / len) * move;
    }
    temperature = Math.max(0.5, temperature * 0.97);
  }
  const xs = pos.map((p) => p[0]);
  const ys = pos.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = 64; // Platz für Beschriftungen am Rand
  const scale = Math.min((width - pad * 2) / Math.max(maxX - minX, 1), (height - pad * 2) / Math.max(maxY - minY, 1), 1.6);
  const offX = (width - (maxX - minX) * scale) / 2;
  const offY = (height - (maxY - minY) * scale) / 2;
  return pos.map(([x, y]) => [offX + (x - minX) * scale, offY + (y - minY) * scale]);
}

function renderGraph() {
  const box = $("#noteGraph");
  if (!memoryUI.data) return;
  let { nodes, links } = memoryUI.data.graph;
  if (!nodes.length) {
    box.innerHTML = `<div class="graph-empty">Noch keine Notizen – der Graph wächst mit jeder Verknüpfung.</div>`;
    return;
  }
  const degree = new Map(nodes.map((node) => [node.id, 0]));
  for (const l of links) {
    degree.set(l.source, (degree.get(l.source) || 0) + 1);
    degree.set(l.target, (degree.get(l.target) || 0) + 1);
  }
  if (nodes.length > 300) { // große Tresore: die am stärksten verknüpften Notizen
    nodes = [...nodes].sort((a, b) => degree.get(b.id) - degree.get(a.id)).slice(0, 300);
    const keep = new Set(nodes.map((node) => node.id));
    links = links.filter((l) => keep.has(l.source) && keep.has(l.target));
  }
  const width = box.clientWidth || 900;
  const height = box.clientHeight || 560;
  const pos = layoutGraph(nodes, links, width, height);
  const at = new Map(nodes.map((node, i) => [node.id, pos[i]]));
  const lines = links.map((l) => {
    const [a, b] = [at.get(l.source), at.get(l.target)];
    return a && b ? `<line class="graph-link" data-a="${esc(l.source)}" data-b="${esc(l.target)}" x1="${a[0].toFixed(1)}" y1="${a[1].toFixed(1)}" x2="${b[0].toFixed(1)}" y2="${b[1].toFixed(1)}"/>` : "";
  }).join("");
  const dots = nodes.map((node, i) => {
    const r = 4 + Math.min(8, Math.sqrt(degree.get(node.id) || 0) * 1.8);
    const hub = (degree.get(node.id) || 0) >= 3 || node.pinned;
    return `<g class="graph-node ${node.vault}${node.pinned ? " pinned" : ""}${hub ? " hub" : ""}" data-id="${esc(node.id)}" data-title="${esc(node.title)}" data-vault="${node.vault}"
      transform="translate(${pos[i][0].toFixed(1)} ${pos[i][1].toFixed(1)})" tabindex="0" role="button" aria-label="${esc(node.title)}">
      <circle r="${r.toFixed(1)}"/><text y="${(r + 14).toFixed(1)}">${esc(node.title)}</text></g>`;
  }).join("");
  box.classList.toggle("dense", nodes.length > 60);
  box.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Graph der Notizen">${lines}${dots}</svg>
    <div class="graph-legend"><span><i class="project"></i>Projekt</span><span><i></i>Global</span><span><i class="library"></i>Bibliothek</span><span><i class="missing"></i>Noch nicht angelegt</span></div>`;
}

$$("#memorySheet .sheet-head .view-switch button").forEach((b) => b.addEventListener("click", () => setMemoryView(b.dataset.view)));
$("#noteSearch").addEventListener("input", (e) => {
  memoryUI.query = e.target.value.trim();
  if (memoryUI.data) renderNoteList();
});
$("#noteNew").addEventListener("click", () => editNote(null));
$("#memoryBtn").addEventListener("click", () => openMemory());
$("#memoryBody").addEventListener("submit", (e) => {
  if (e.target.id !== "noteForm") return;
  e.preventDefault();
  saveNote(e.target);
});
$("#memoryBody").addEventListener("click", (e) => {
  const tag = e.target.closest("[data-tag]");
  const row = e.target.closest(".note-row");
  const vault = e.target.closest("#noteForm [data-vault]");
  if (tag) {
    memoryUI.tag = memoryUI.tag === tag.dataset.tag ? null : tag.dataset.tag;
    renderNoteList();
    $("#memoryBody").classList.remove("reading");
  } else if (row) {
    showNote(row.dataset.note, row.dataset.vault);
  } else if (vault) {
    $$("#noteForm [data-vault]").forEach((b) => b.setAttribute("aria-checked", String(b === vault)));
  } else if (e.target.closest("[data-back]")) {
    $("#memoryBody").classList.remove("reading");
  } else if (e.target.closest("[data-note-edit]")) {
    editNote(memoryUI.note);
  } else if (e.target.closest("[data-note-pin]")) {
    togglePin(memoryUI.note);
  } else if (e.target.closest("[data-note-delete]")) {
    deleteNote(memoryUI.note);
  } else if (e.target.closest("[data-note-copy]")) {
    copyNote(memoryUI.note);
  } else if (e.target.closest("[data-note-create]")) {
    editNote(null);
  } else if (e.target.closest("[data-note-cancel]")) {
    if (memoryUI.current && memoryUI.note) showNote(memoryUI.note.title, memoryUI.note.vault);
    else renderNoteEmpty();
  }
});

const graphBox = $("#noteGraph");
graphBox.addEventListener("mouseover", (e) => {
  const node = e.target.closest(".graph-node");
  if (!node) return;
  const near = new Set([node.dataset.id]);
  $$(".graph-link", graphBox).forEach((line) => {
    const touches = line.dataset.a === node.dataset.id || line.dataset.b === node.dataset.id;
    line.classList.toggle("near", touches);
    if (touches) near.add(line.dataset.a).add(line.dataset.b);
  });
  $$(".graph-node", graphBox).forEach((dot) => dot.classList.toggle("near", near.has(dot.dataset.id)));
  graphBox.classList.add("focus");
});
graphBox.addEventListener("mouseout", (e) => {
  if (!e.relatedTarget?.closest?.(".graph-node")) graphBox.classList.remove("focus");
});
graphBox.addEventListener("click", (e) => {
  const node = e.target.closest(".graph-node");
  if (!node) return;
  setMemoryView("notes");
  showNote(node.dataset.title, node.dataset.vault);
});
graphBox.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.closest(".graph-node")) e.target.closest(".graph-node").dispatchEvent(new MouseEvent("click", { bubbles: true }));
});

/* ================================================================ Agents */

const TOOL_GROUPS = [
  { id: "read", label: "Lesen", sub: "Dateien lesen und durchsuchen", icon: "read_file", tools: ["read_file", "list_dir", "glob", "grep"] },
  { id: "edit", label: "Bearbeiten", sub: "Dateien ändern und anlegen", icon: "edit_file", tools: ["edit_file", "write_file"] },
  { id: "terminal", label: "Terminal", sub: "Befehle, Tests und Builds", icon: "run_command", tools: ["run_command"] },
  { id: "web", label: "Internet", sub: "Suchen und Seiten lesen", icon: "web_search", tools: ["web_search", "web_fetch"] },
];
const SOURCE_LABEL = {
  project: "Dieses Projekt", "claude-project": "Dieses Projekt · Claude Code", global: "Eigene",
  claude: "Aus Claude Code", builtin: "Eingebaut",
};

function toolPills(tools) {
  if (tools == null) return `<span class="tool-pill">Alle Werkzeuge</span>`;
  const groups = TOOL_GROUPS.filter((g) => g.tools.some((t) => tools.includes(t)));
  return groups.map((g) => `<span class="tool-pill">${g.label}</span>`).join("") || `<span class="tool-pill">Keine Werkzeuge</span>`;
}

async function openAgents() {
  openSheet("#agentsSheet");
  $("#agentNew").hidden = false;
  $("#agentsBody").innerHTML = `<div class="model-empty"><span class="spinner"></span></div>`;
  try {
    renderAgents(await loadExtensions(true));
  } catch (e) {
    $("#agentsBody").innerHTML = `<div class="model-empty">${esc(e.message)}</div>`;
  }
}

function renderAgents(ext) {
  $("#agentNew").hidden = false;
  const groups = Object.keys(SOURCE_LABEL)
    .map((source) => [source, ext.agents.filter((a) => a.source === source)])
    .filter(([, list]) => list.length);
  $("#agentsBody").innerHTML = groups.map(([source, list]) => `
    <section class="agents-group">
      <span class="eyebrow">${SOURCE_LABEL[source]}</span>
      <div class="list">${list.map((a) => `
        <div class="agent-row">
          <span class="agent-avatar" aria-hidden="true">${esc(a.name.replace(/[^a-z0-9]/gi, "").slice(0, 2))}</span>
          <div>
            <div class="agent-name">@${esc(a.name)}</div>
            <div class="agent-desc" title="${esc(a.description)}">${esc(a.description)}</div>
            <div class="agent-tools">${toolPills(a.tools)}</div>
          </div>
          <div class="agent-actions">
            <button class="btn ghost" type="button" data-agent-use="${esc(a.name)}">Ansprechen</button>
            <button class="btn" type="button" data-agent-edit="${esc(a.name)}">${a.editable ? "Bearbeiten" : "Anpassen"}</button>
          </div>
        </div>`).join("")}
      </div>
    </section>`).join("") + `
    <p class="agents-hint">Coder gibt Teilaufgaben selbst an passende Agents ab. Mit <code>@name</code> am Anfang einer Nachricht
    übernimmt ein Agent den ganzen Auftrag. Eigene Agents liegen als Markdown in <code>~/.coder/agents</code> oder im Projekt
    unter <code>.coder/agents</code>.</p>`;
}

function agentEditor(agent) {
  const a = agent || { name: "", description: "", prompt: "", tools: TOOL_GROUPS[0].tools, source: "global", editable: true };
  const isNew = !agent;
  const scope = a.editable ? a.source : "global";
  const has = (g) => a.tools == null || g.tools.some((t) => a.tools.includes(t));
  $("#agentNew").hidden = true;
  $("#agentsBody").innerHTML = `
    <form class="settings agent-editor" id="agentForm" autocomplete="off">
      <span class="eyebrow">${isNew ? "Neuer Agent" : a.editable ? "Agent bearbeiten" : `Anpassen – eigene Fassung von @${esc(a.name)}`}</span>
      <div class="list">
        <label class="row col"><span>Name</span>
          <span class="name-field"><span>@</span><input name="name" value="${esc(a.name)}" spellcheck="false" maxlength="40" placeholder="api-tester"></span>
        </label>
        <label class="row col"><span>Wann soll Coder ihn einsetzen?</span>
          <textarea name="description" rows="2" placeholder="Eine Zeile: wofür er da ist und was er liefert">${esc(a.description)}</textarea>
        </label>
      </div>
      <span class="eyebrow">Werkzeuge</span>
      <div class="choice-grid">${TOOL_GROUPS.map((g) => `
        <label class="choice"><input type="checkbox" name="tools" value="${g.id}"${has(g) ? " checked" : ""}>
          <span class="choice-card">${ICONS[g.icon]}<span><strong>${g.label}</strong><small>${g.sub}</small></span></span>
        </label>`).join("")}
      </div>
      <span class="eyebrow">Anweisungen</span>
      <textarea class="prompt" name="prompt" rows="10" spellcheck="false" placeholder="Du bist … Gehe so vor: …">${esc(a.prompt)}</textarea>
      <span class="eyebrow">Speichern für</span>
      <div class="choice-grid">
        <label class="choice"><input type="radio" name="scope" value="global"${scope === "global" ? " checked" : ""}>
          <span class="choice-card">${ICONS.agent}<span><strong>Alle Projekte</strong><small>~/.coder/agents</small></span></span></label>
        <label class="choice"><input type="radio" name="scope" value="project"${scope === "project" ? " checked" : ""}>
          <span class="choice-card">${ICONS.folder}<span><strong>Dieses Projekt</strong><small>.coder/agents im Workspace</small></span></span></label>
      </div>
      <p class="form-error" id="agentError" role="alert"></p>
      <div class="sheet-actions">
        ${!isNew && a.editable ? `<button type="button" class="btn ghost danger" id="agentDelete">Löschen</button><span class="spacer"></span>` : ""}
        <button type="button" class="btn ghost" id="agentBack">Zurück</button>
        <button type="submit" class="btn primary">Sichern</button>
      </div>
    </form>`;
  const form = $("#agentForm");
  form.elements.name.focus();
  $("#agentBack").addEventListener("click", () => renderAgents(state.ext));
  $("#agentDelete")?.addEventListener("click", () => deleteAgent(a));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    saveAgent(form, a);
  });
}

async function saveAgent(form, original) {
  const picked = new Set($$("input[name=tools]:checked", form).map((i) => i.value));
  const body = {
    name: form.elements.name.value.trim().replace(/^@/, "").toLowerCase(),
    description: form.elements.description.value,
    prompt: form.elements.prompt.value,
    // Alle Gruppen gewählt heißt: alle Werkzeuge, auch künftige
    tools: picked.size === TOOL_GROUPS.length ? null : TOOL_GROUPS.filter((g) => picked.has(g.id)).flatMap((g) => g.tools),
    scope: $("input[name=scope]:checked", form)?.value || "global",
    workspace: currentWorkspace(),
  };
  if (original.editable && original.name) Object.assign(body, { original: original.name, original_scope: original.source });
  const btn = $("button[type=submit]", form);
  btn.disabled = true;
  try {
    const saved = await api("/api/agents", { method: "POST", body });
    toast(`@${saved.name} gesichert`);
    renderAgents(await loadExtensions(true));
  } catch (e) {
    $("#agentError").textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function deleteAgent(agent) {
  if (!confirm(`@${agent.name} löschen?`)) return;
  try {
    const q = `?workspace=${encodeURIComponent(currentWorkspace())}`;
    await api(`/api/agents/${agent.source}/${encodeURIComponent(agent.name)}${q}`, { method: "DELETE" });
    toast(`@${agent.name} gelöscht`);
    renderAgents(await loadExtensions(true));
  } catch (e) {
    $("#agentError").textContent = e.message;
  }
}

$("#agentsBody").addEventListener("click", (e) => {
  const use = e.target.closest("[data-agent-use]");
  const edit = e.target.closest("[data-agent-edit]");
  if (use) {
    closeSheets();
    input.value = `@${use.dataset.agentUse} ${input.value.replace(/^@[\w-]+\s*/, "")}`;
    autosize();
    updateSendState();
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
  } else if (edit) {
    agentEditor(state.ext.agents.find((a) => a.name === edit.dataset.agentEdit));
  }
});
$("#agentNew").addEventListener("click", () => agentEditor(null));
$("#agentsBtn").addEventListener("click", openAgents);

/* ================================================================ Globale Aktionen */

function toggleSidebar() {
  const app = $("#app");
  if (matchMedia("(max-width: 760px)").matches) {
    app.classList.toggle("open");
  } else {
    app.classList.toggle("collapsed");
    store.set("coder.sidebar", app.classList.contains("collapsed") ? "0" : "1");
  }
}

$("#newChat").addEventListener("click", () => {
  if (state.busy) return toast("Der Agent arbeitet noch.");
  send({ type: "new" });
  input.focus();
});
$("#modelBtn").addEventListener("click", openModels);
$("#settingsBtn").addEventListener("click", () => openSettings());
$("#workspaceBtn").addEventListener("click", openWorkspace);
$("#wsChip").addEventListener("click", openWorkspace);
$("#settingsWorkspace").addEventListener("click", () => { closeSheets(); openWorkspace(); });
$("#search").addEventListener("input", renderSessions);
const MODES = ["ask", "auto-edit", "plan", "yolo"];
$("#modeSeg").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.classList.contains("on") && matchMedia("(max-width: 560px)").matches) {
    // Schmal ist nur der aktive Modus sichtbar: Tippen schaltet zum nächsten.
    const next = MODES[(MODES.indexOf(b.dataset.mode) + 1) % MODES.length];
    setMode(next);
    toast(`Modus: ${$(`#modeSeg [data-mode="${next}"]`).getAttribute("aria-label")}`);
    return;
  }
  setMode(b.dataset.mode);
});
$("#sidebarToggle").addEventListener("click", toggleSidebar);
$("#scrim").addEventListener("click", () => $("#app").classList.remove("open"));
window.addEventListener("resize", () => setMode(state.config?.permission_mode || "ask", false));

document.addEventListener("keydown", (e) => {
  const mod = e.ctrlKey || e.metaKey;
  const sheetOpen = $$(".sheet-backdrop:not([hidden])").length > 0;
  const key = e.key.toLowerCase();
  if (e.key === "Escape") {
    if (!$("#lightbox").hidden) return ($("#lightbox").hidden = true);
    if (!$("#palette").hidden) return closePalette();
    if (sheetOpen) return closeSheets();
    if (state.approvalId) return answerApproval("deny");
    if ($("#app").classList.contains("open")) return $("#app").classList.remove("open");
    if (state.busy) send({ type: "cancel" });
  } else if (mod && e.key === "Enter" && state.approvalId && !sheetOpen) {
    e.preventDefault();
    answerApproval("allow");
  } else if (mod && key === "n") {
    e.preventDefault();
    $("#newChat").click();
  } else if (mod && key === "m") {
    e.preventDefault();
    openModels();
  } else if (mod && key === "o") {
    e.preventDefault();
    if (!sheetOpen) openWorkspace();
  } else if (mod && key === "k") {
    e.preventDefault();
    togglePalette();
  } else if (mod && key === "b") {
    e.preventDefault();
    toggleSidebar();
  } else if (mod && e.key === ",") {
    e.preventDefault();
    openSettings();
  }
});

/* ================================================================ Befehlspalette */

const palette = { items: [], index: 0, returnFocus: null };
const MODE_NAMES = { ask: "Fragen", "auto-edit": "Auto-Edit", plan: "Planen", yolo: "Autonom" };
const PALETTE_GROUPS = ["Aktionen", "Befehle", "Agents", "Notizen", "Chats", "Modus"];

function togglePalette() {
  if ($("#palette").hidden) openPalette();
  else closePalette();
}

async function openPalette() {
  palette.returnFocus = document.activeElement;
  palette.index = 0;
  $("#palette").hidden = false;
  $("#paletteInput").value = "";
  renderPalette();
  $("#paletteInput").focus();
  await Promise.allSettled([loadExtensions(), loadNotes()]);
  if (!$("#palette").hidden) renderPalette();
}

function closePalette() {
  $("#palette").hidden = true;
  palette.returnFocus?.focus?.();
}

function insertIntoInput(text) {
  input.value = text;
  autosize();
  updateSendState();
  input.focus();
  input.setSelectionRange(text.length, text.length);
}

function paletteEntries() {
  const action = (icon, label, run, hint = "") => ({ group: "Aktionen", icon: ICONS[icon], label, run, hint });
  const entries = [
    action("plus", "Neuer Chat", () => $("#newChat").click(), "Strg N"),
    action("list_dir", "Workspace wählen", openWorkspace, "Strg O"),
    action("chip", "Modell wählen", openModels, "Strg M"),
    action("graph", "Gedächtnis öffnen", () => openMemory()),
    action("agent", "Agents verwalten", openAgents),
    action("image", "Bild anhängen", () => $("#fileInput").click()),
    action("compact", "Verlauf verdichten", () => send({ type: "compact" })),
    action("undo", "Letzte Änderungen zurücknehmen", undoLast),
    action("copy", "Chat als Markdown kopieren", copyChat),
    action("sidebar", "Seitenleiste ein- oder ausblenden", toggleSidebar, "Strg B"),
    action("gear", "Einstellungen", openSettings, "Strg ,"),
  ];
  for (const c of state.ext?.commands || []) {
    entries.push({ group: "Befehle", icon: ICONS.command, label: `/${c.name}`, mono: true, desc: c.description, run: () => insertIntoInput(`/${c.name} `) });
  }
  for (const a of state.ext?.agents || []) {
    entries.push({ group: "Agents", icon: ICONS.agent, label: `@${a.name}`, mono: true, desc: a.description, run: () => insertIntoInput(`@${a.name} `) });
  }
  for (const n of memoryUI.data?.notes || []) {
    entries.push({ group: "Notizen", icon: ICONS.note, label: n.title, desc: vaultLabel(n.vault), run: () => openMemory({ title: n.title, vault: n.vault }) });
  }
  for (const s of state.sessions || []) {
    entries.push({
      group: "Chats", icon: ICONS.chat, label: s.title || "Ohne Titel", desc: [whenLabel(s.updated), basename(s.workspace)].filter(Boolean).join(" · "),
      run: () => (state.busy ? toast("Der Agent arbeitet noch.") : send({ type: "open", session_id: s.id })),
    });
  }
  for (const mode of MODES) {
    entries.push({ group: "Modus", icon: ICONS.mode, label: MODE_NAMES[mode], desc: state.config?.permission_mode === mode ? "aktiv" : "", run: () => setMode(mode) });
  }
  return entries;
}

function paletteScore(entry, query) {
  const label = entry.label.toLowerCase();
  const at = label.indexOf(query);
  if (at === 0 || (at === 1 && /^[/@]/.test(label))) return 100;
  if (at > 0) return 70 - Math.min(at, 40);
  if ((entry.desc || "").toLowerCase().includes(query)) return 20;
  let pos = 0; // Buchstaben in Reihenfolge: „nc“ findet „Neuer Chat“
  for (const ch of query) {
    pos = label.indexOf(ch, pos);
    if (pos < 0) return 0;
    pos++;
  }
  return 10;
}

function renderPalette() {
  const query = $("#paletteInput").value.trim().toLowerCase();
  const entries = paletteEntries();
  const items = query
    ? entries.map((entry) => [entry, paletteScore(entry, query)]).filter(([, score]) => score > 0)
      .sort((a, b) => b[1] - a[1]).slice(0, 40).map(([entry]) => entry)
    : PALETTE_GROUPS.flatMap((group) => entries.filter((e) => e.group === group).slice(0, group === "Aktionen" ? 11 : 5));
  palette.items = items;
  palette.index = Math.max(0, Math.min(palette.index, items.length - 1));
  let group = null;
  $("#paletteList").innerHTML = items.map((item, i) => {
    const head = !query && item.group !== group ? `<span class="palette-group eyebrow">${item.group}</span>` : "";
    group = item.group;
    const desc = query ? [item.desc, item.group].filter(Boolean).join(" · ") : item.desc || "";
    return `${head}<button type="button" class="palette-item" role="option" data-i="${i}" aria-selected="${i === palette.index}">
      ${item.icon}<span class="palette-label${item.mono ? " mono" : ""}">${esc(item.label)}</span>
      <span class="palette-desc">${esc(desc)}</span>${item.hint ? `<kbd>${esc(item.hint)}</kbd>` : "<span></span>"}
    </button>`;
  }).join("") || `<div class="palette-empty">Nichts gefunden.</div>`;
  $(`#paletteList [data-i="${palette.index}"]`)?.scrollIntoView({ block: "nearest" });
}

function runPalette(i = palette.index) {
  const item = palette.items[i];
  if (!item) return;
  closePalette();
  item.run();
}

$("#paletteInput").addEventListener("input", () => {
  palette.index = 0;
  renderPalette();
});
$("#paletteInput").addEventListener("keydown", (e) => {
  const n = palette.items.length;
  if ((e.key === "ArrowDown" || e.key === "ArrowUp") && n) {
    e.preventDefault();
    palette.index = (palette.index + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
    $$("#paletteList .palette-item").forEach((row) => row.setAttribute("aria-selected", String(Number(row.dataset.i) === palette.index)));
    $(`#paletteList [data-i="${palette.index}"]`)?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter") {
    e.preventDefault();
    runPalette();
  }
});
$("#paletteList").addEventListener("mousedown", (e) => e.preventDefault());
$("#paletteList").addEventListener("click", (e) => {
  const row = e.target.closest("[data-i]");
  if (row) runPalette(Number(row.dataset.i));
});
$("#palette").addEventListener("mousedown", (e) => { if (e.target.id === "palette") closePalette(); });

/* ================================================================ Start */

async function loadState() {
  try {
    const s = await api("/api/state");
    state.config = s.config;
    state.hardware = s.hardware;
    state.ollama = s.ollama;
    state.loaded = s.loaded;
    state.sessions = s.sessions;
    state.nativePicker = !!s.native_picker;
    updateWorkspace();
    updateModelPill();
    setMode(s.config.permission_mode, false);
    renderSessions();
    if (!s.ollama.ok) toast("Ollama ist nicht erreichbar – starte Ollama.", { error: true, ms: 6000 });
  } catch (e) {
    toast(`Server nicht erreichbar: ${e.message}`, { error: true, ms: 6000 });
  }
}

(async function init() {
  if (store.get("coder.sidebar") === "0") $("#app").classList.add("collapsed");
  await loadState();
  connect();
  updatePlaceholder();
  autosize();
  updateSendState();
  setContext(null);
  input.focus();
  setInterval(() => { if (!state.busy) refreshLoaded(); }, 20000);
  document.fonts?.ready.then(() => setMode(state.config?.permission_mode || "ask", false));
})();
