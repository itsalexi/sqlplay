// psqlay web — minimalist terminal front end. No framework.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
const MOD = isMac ? "⌘" : "Ctrl";
const ALT = isMac ? "⌥" : "Alt+";

let S = null;            // last /api/state
let mode = "practice";   // practice | exam | report
let examIndex = 0;
let examDrafts = {};
let timer = null;
let passed = false;
let lastSQL = "";

// ------------------------------------------------------------------ utils
async function api(path, body) {
  const opts = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json", "X-Psqlay": "1" }, body: JSON.stringify(body) };
  const r = await fetch("/api/" + path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function toast(msg, { ms = 2600, spin = false } = {}) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (spin ? " spin" : "");
  t.hidden = false;
  clearTimeout(toast.h);
  if (ms) toast.h = setTimeout(() => (t.hidden = true), ms);
}
const untoast = () => ($("toast").hidden = true);

function sheet({ html, ok = "OK", cancel = "Cancel", onOk, onOpen }) {
  $("sheet-body").innerHTML = html;
  $("sheet-ok").textContent = ok;
  $("sheet-cancel").hidden = !cancel;
  $("sheet-cancel").textContent = cancel || "";
  $("sheet").hidden = false;
  const close = () => { $("sheet").hidden = true; document.removeEventListener("keydown", onKey, true); };
  const onKey = (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(); }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("sheet-ok").click(); }
  };
  document.addEventListener("keydown", onKey, true);
  $("sheet-cancel").onclick = close;
  $("sheet-ok").onclick = () => { close(); onOk && onOk(); };
  onOpen && onOpen();
}

function confirmSheet(title, text, ok, onOk) {
  sheet({ html: `<h3>${esc(title)}</h3><p>${esc(text)}</p>`, ok, onOk });
}

// psql-style text table
function psqlTable(columns, rows, truncated, numeric) {
  numeric = numeric || columns.map((_, i) => rows.some((r) => typeof r[i] === "number"));
  const cell = (v) => (v === null ? "" : String(v));
  const cells = rows.map((r) => r.map(cell));
  const w = columns.map((c, i) => Math.max(c.length, ...cells.map((r) => r[i].length)));
  const head = columns.map((c, i) => {
    const pad = w[i] - c.length, l = Math.floor(pad / 2);
    return " ".repeat(l) + esc(c) + " ".repeat(pad - l);
  }).join(" | ");
  const rule = w.map((n) => "-".repeat(n)).join("-+-");
  const body = rows.map((r, ri) => " " + r.map((v, i) => {
    const s = cells[ri][i], pad = " ".repeat(w[i] - s.length);
    const txt = v === null ? "" : esc(s);
    return numeric[i] ? pad + txt : txt + pad;
  }).join(" | ").replace(/\s+$/, "")).join("\n");
  const n = rows.length;
  const foot = `(${n} row${n === 1 ? "" : "s"}${truncated ? ", showing first 500" : ""})`;
  return `<pre class="table"><span class="h"> ${head}</span>\n<span class="rule">-${rule}-</span>\n${body}${n ? "\n" : ""}<span class="foot">${foot}</span></pre>`;
}

function lessonHTML(l) {
  const rows = [["why", "explain"], ["e.g.", "example"], ["look", "nudge"], ["try", "try"]]
    .filter(([, k]) => l[k])
    .map(([label, k]) => `<dt class="${k}">${label}</dt><dd class="${k}">${k === "example" ? `<code>${esc(l[k])}</code>` : esc(l[k])}</dd>`)
    .join("");
  return `<div class="ai lesson"><span class="tag">AI</span><div class="txt">
    ${l.concept ? `<div class="concept">${esc(l.concept)}</div>` : ""}<dl>${rows}</dl></div></div>`;
}

function diffHTML(v) {
  const parts = [];
  const res = v.result || {};
  if (v.missing && v.missing.length)
    parts.push(`<div class="lbl miss">missing · expected but not in yours</div>${psqlTable(v.expected_columns, v.missing, false, v.expected_numeric).replace(/<span class="foot">.*?<\/span>/, "")}`);
  if (v.extra && v.extra.length && res.columns)
    parts.push(`<div class="lbl extra">extra · yours but not expected</div>${psqlTable(res.columns, v.extra, false, res.numeric).replace(/<span class="foot">.*?<\/span>/, "")}`);
  return parts.length ? `<div class="diff">${parts.join("")}</div>` : "";
}

function resultHTML(res) {
  if (!res) return "";
  if (res.error) return `<pre class="err">${esc(res.error)}</pre>`;
  return psqlTable(res.columns, res.rows, res.truncated, res.numeric);
}

// ------------------------------------------------------------------ editor
const ta = () => $("sql");
const hist = { list: JSON.parse(localStorage.getItem("psqlay.history") || "[]"), i: -1, draft: "" };
function remember(sql) {
  sql = sql.trim();
  if (!sql) return;
  hist.list = [sql, ...hist.list.filter((q) => q !== sql)].slice(0, 100);
  localStorage.setItem("psqlay.history", JSON.stringify(hist.list));
  hist.i = -1;
}
function historyStep(dir) {
  if (!hist.list.length) return;
  if (hist.i === -1) hist.draft = ta().value;
  hist.i = Math.max(-1, Math.min(hist.list.length - 1, hist.i + dir));
  setEditor(hist.i === -1 ? hist.draft : hist.list[hist.i]);
}

function promptName() {
  const slug = (S && (S.exam ? S.exam.world : S.status.world.slug)) || "psqlay";
  return slug;
}

function syncEditor() {
  const t = ta();
  const lines = Math.max(3, t.value.split("\n").length);
  const name = promptName();
  const first = `${name}=#`, rest = `${name}-#`;
  $("gutter").textContent = [first, ...Array(lines - 1).fill(rest)].join("\n");
  t.style.height = "auto";
  t.style.height = t.scrollHeight + "px";
}

function setEditor(v) { ta().value = v || ""; syncEditor(); }

function renderKeys() {
  const k = $("keys");
  if (mode === "exam") {
    k.innerHTML = `
      <button data-act="prev"><kbd>${ALT}←</kbd>prev</button>
      <button data-act="next"><kbd>${ALT}→</kbd>next</button>`;
    $("run-btn").innerHTML = `Save <kbd>${MOD}↵</kbd>`;
  } else {
    const used = S?.level?.hints_used?.length || 0, total = S?.level?.hint_count || 0;
    k.innerHTML = `
      <button data-act="hint" ${used >= total ? "disabled" : ""}><kbd>${ALT}H</kbd>hint ${used}/${total}</button>
      <button data-act="answer"><kbd>${ALT}A</kbd>give up</button>
      <button data-act="skip"><kbd>${ALT}S</kbd>skip</button>
      <button data-act="hist" title="previous queries"><kbd>${ALT}↑↓</kbd>history</button>`;
    $("run-btn").innerHTML = `Run <kbd>${MOD}↵</kbd>`;
  }
  k.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => act(b.dataset.act)));
}

function act(a) {
  ({
    hint, answer: giveUp, skip: nextLevel, hist: () => historyStep(1),
    prev: () => examGo(examIndex - 1), next: () => examGo(examIndex + 1),
  })[a]?.();
}

// ------------------------------------------------------------------ render
function bump(id, value) {
  const el = $(id);
  if (el.textContent !== String(value)) {
    el.textContent = value;
    el.classList.add("bump");
    setTimeout(() => el.classList.remove("bump"), 900);
  }
}

function renderBar() {
  const st = S.status;
  bump("score", st.score);
  bump("streak", st.streak);
  const dot = $("ai-dot");
  dot.className = "ai-dot" + (st.ai && (st.ai_feedback || st.ai_levels) ? " on" : "");
  dot.title = S.models ? `generate: ${S.models.generate}\nfeedback: ${S.models.feedback}` : "Add OPENAI_API_KEY to .env to enable AI";
  $("newworld-btn").hidden = !st.ai;
  $("world-emoji").textContent = st.world.emoji || "";
  $("world").innerHTML = S.worlds.map((w) =>
    `<option value="${esc(w.slug)}" ${w.slug === st.world.slug ? "selected" : ""}>${esc(w.name)}${w.source === "ai" ? "  · ai" : ""}</option>`).join("");
  $("topic").innerHTML = [`<option value="">mix</option>`].concat(
    st.topics.filter((t) => t.unlocked).map((t) =>
      `<option value="${t.topic}" ${st.locked === t.topic ? "selected" : ""}>${esc(t.name.toLowerCase())}</option>`)).join("");
  autosize($("world")); autosize($("topic"));
}

function autosize(sel) {
  const span = document.createElement("span");
  span.style.cssText = "position:absolute;visibility:hidden;white-space:pre;font:inherit";
  span.textContent = sel.options[sel.selectedIndex]?.text || "";
  sel.parentNode.appendChild(span);
  sel.style.width = span.offsetWidth + 6 + "px";
  span.remove();
}

function renderRail() {
  const open = new Set([...document.querySelectorAll(".tbl.open")].map((e) => e.dataset.t));
  const first = !$("schema").children.length;
  $("schema").innerHTML = S.schema.map((t, i) => `
    <div class="tbl ${open.has(t.table) || (first && i < 2) ? "open" : ""}" data-t="${esc(t.table)}">
      <button><span class="chev">›</span>${esc(t.table)}<span class="n">${t.rows}</span></button>
      <div class="cols">${t.columns.map((c) => `
        <div class="col" data-col="${esc(c.name)}" title="${c.fk ? "→ " + esc(c.fk) : ""}">
          <span>${esc(c.name)} ${c.pk ? '<span class="k">●</span>' : c.fk ? '<span class="f">→</span>' : ""}</span>
          <span class="t">${esc(c.type)}</span>
        </div>`).join("")}</div>
    </div>`).join("");
  $("schema").querySelectorAll(".tbl > button").forEach((b) => (b.onclick = () => b.parentNode.classList.toggle("open")));
  $("schema").querySelectorAll(".col").forEach((c) => (c.onclick = () => insert(c.dataset.col)));
  $("joinmap").innerHTML = joinMapHTML(S.join_map || "");
  const notes = (S.notes || "").trim();
  $("notes").innerHTML = notes ? `<details><summary> data notes</summary><div>${esc(notes)}</div></details>` : "";
  const ss = S.status.session;
  if (ss && (ss.attempts || ss.missed)) {
    const mins = Math.max(1, Math.round((Date.now() / 1000 - ss.started) / 60));
    $("session").innerHTML = `this session · <b>${ss.passed}</b> solved · ${ss.missed} missed · <b>+${ss.points}</b> pts · ${mins} min`;
  } else $("session").innerHTML = "";
  $("levels").innerHTML = S.status.topics.map((t) => `
    <div class="lv ${t.unlocked ? "" : "locked"}" title="${t.unlocked ? `${t.passed} passed of ${t.attempted}` : "unlocks after 3 aggregate passes"}">
      <span class="name">${esc(t.name.toLowerCase())}</span><span class="val">L${t.difficulty}</span>
      <span class="track"><i style="width:${t.difficulty * 20}%"></i></span>
    </div>`).join("");
}

// "a -col- b -col- c" -> one table per line, link column dimmed; "t.x -> t.y" kept as a self-ref line
function joinMapHTML(text) {
  return text.trim().split("\n").filter(Boolean).map((line) => {
    line = line.trim();
    const self = line.match(/^(\w+)\.(\w+)\s*->\s*(\w+)\.(\w+)$/);
    if (self) {
      return `<div class="jm"><span class="jt">${esc(self[1])}</span><span class="jc">.${esc(self[2])} → .${esc(self[4])}</span><span class="jself">self</span></div>`;
    }
    const parts = line.split(/\s+-(\w+)-\s+/);
    if (parts.length < 3) return `<div class="jm"><span class="jc">${esc(line)}</span></div>`;
    let html = `<div class="jm"><span class="jt">${esc(parts[0])}</span>`;
    for (let i = 1; i < parts.length; i += 2) {
      html += `<div class="jhop"><span class="jc">${esc(parts[i])}</span><span class="jt">${esc(parts[i + 1])}</span></div>`;
    }
    return html + "</div>";
  }).join("");
}

function renderQuestion(lv, metaText) {
  $("q-dots").innerHTML = [1, 2, 3, 4, 5].map((i) => `<i class="${i <= lv.difficulty ? "on" : ""}"></i>`).join("");
  $("q-meta").textContent = metaText;
  $("q-text").textContent = lv.question;
  const rows = [];
  if (lv.columns && lv.columns.length) rows.push(["columns", lv.columns.map((c) => `<code>"${esc(c)}"</code>`).join(", ")]);
  if (lv.ordered && lv.order_note) rows.push(["sort", esc(lv.order_note)]);
  $("q-reqs").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  renderExpected(lv.expected);
  renderQbar(lv, metaText, rows);
}

// ---- pinned question bar
let qbarExp = null;   // null = follow the "show expected output" setting
const qbExpOn = () => (qbarExp === null ? !!S.status.show_expected : qbarExp);
function renderQbar(lv, metaText, rows) {
  $("qb-dots").innerHTML = $("q-dots").innerHTML;
  $("qb-meta").textContent = metaText;
  $("qb-text").textContent = lv.question;
  $("qb-text").classList.remove("full");
  $("qb-reqs").innerHTML = rows.map(([k, v]) => `${k} ${v}`).join(" &nbsp;·&nbsp; ");
  const exp = lv.expected;
  $("qb-exp").hidden = !exp;
  $("qb-exp").classList.toggle("on", qbExpOn());
  $("qb-expected").hidden = !(exp && qbExpOn());
  if (exp && qbExpOn()) $("qb-expected").innerHTML = psqlTable(exp.columns, exp.rows, false, exp.numeric);
  const pinned = S.status.sticky_question;
  let pin = document.querySelector(".q .meta .pin");
  if (!pinned && !pin) {
    $("q-meta").insertAdjacentHTML("afterend", `<button class="pin" title="Keep the question visible while you scroll">pin question</button>`);
    pin = document.querySelector(".q .meta .pin");
    pin.onclick = async () => { S = await api("setting", { key: "sticky_question", on: true }); pin.remove(); updateQbar(); };
  } else if (pinned && pin) pin.remove();
  updateQbar();
}

let qVisible = true;
function updateQbar() {
  const show = !qVisible && mode !== "report" && S && S.status.sticky_question && $("sheet").hidden;
  $("qbar").hidden = !show;
}
new IntersectionObserver((entries) => { qVisible = entries[0].isIntersecting; updateQbar(); },
  { rootMargin: "-52px 0px 0px 0px" }).observe(document.getElementById("q"));

function renderExpected(exp) {
  const el = $("expected");
  if (!exp) { el.innerHTML = ""; return; }
  const on = S.status.show_expected;
  const n = exp.rows.length;
  el.innerHTML = `
    <div class="exp-head">
      <span>expected output</span><span class="n">${n} row${n === 1 ? "" : "s"}</span>
      <button id="exp-toggle">${on ? "hide" : "show"}</button>
    </div>
    ${on ? psqlTable(exp.columns, exp.rows, false, exp.numeric) : ""}`;
  $("exp-toggle").onclick = async () => {
    stashDraft();
    const keepSQL = ta().value;
    S = await api("expected", { on: !on });
    renderAll();
    if (mode === "practice") setEditor(keepSQL);
  };
}

function renderPractice() {
  const lv = S.level;
  if (!lv) return;
  const src = { generated: " · generated", ai: " · ai" }[lv.source] || "";
  renderQuestion(lv, `level ${lv.difficulty} · ${lv.topic_name.toLowerCase()} · ${lv.points} pts${src}`);
  if (lv.review) $("q-meta").insertAdjacentHTML("beforeend", ` · <span class="review">review: you missed this one before</span>`);
  $("hints").innerHTML = lv.hints_used.map((h, i) => `<div class="hint"><b>hint ${i + 1}</b>${esc(h)}</div>`).join("");
  renderKeys();
  if (lv.groupby_intro) {
    sheet({ html: `<h3>New topic unlocked: GROUP BY / HAVING</h3><pre>${esc(lv.groupby_intro)}</pre>`, ok: "Got it", cancel: null });
  }
}

function renderMode() {
  const exam = mode === "exam";
  $("bar").hidden = exam;
  $("exam-bar").hidden = !exam;
  $("q").hidden = mode === "report";
  $("term").hidden = mode === "report";
  $("out").hidden = mode === "report";
  $("report").hidden = mode !== "report";
}

function renderAll() {
  if (S.exam && mode !== "exam") { mode = "exam"; examIndex = 0; examDrafts = {}; }
  if (!S.exam && mode === "exam") mode = "practice";
  renderMode();
  renderBar();
  renderRail();
  if (mode === "exam") renderExam();
  else if (mode === "practice") renderPractice();
  syncEditor();
}

async function refresh() { S = await api("state"); renderAll(); }

function insert(text) {
  const t = ta(), s = t.selectionStart, e = t.selectionEnd;
  t.value = t.value.slice(0, s) + text + t.value.slice(e);
  t.selectionStart = t.selectionEnd = s + text.length;
  t.focus(); syncEditor();
}

function shake() { const t = $("term"); t.classList.remove("bad"); void t.offsetWidth; t.classList.add("bad"); }

// ------------------------------------------------------------------ practice
async function run() {
  if (mode === "exam") return examSave();
  const sql = ta().value.trim();
  if (!sql) return;
  if (passed) { /* re-running after a pass is fine */ }
  lastSQL = sql;
  remember(sql);
  $("run-btn").disabled = true;
  try {
    const out = await api("submit", { sql });
    if (out.broken) { toast(out.message, { ms: 5000 }); return; }
    const v = out.verdict;
    S.status = out.status;
    renderBar(); renderRail();
    const table = resultHTML(v.result);
    if (v.passed) {
      passed = true;
      $("term").classList.add("ok");
      let extra = "";
      if (out.first_pass && out.outcome) {
        const o = out.outcome;
        extra = `+${o.points} pts`;
        if (o.difficulty_after > o.difficulty_before) extra += ` · ${esc(S.level.topic_name.toLowerCase())} → level ${o.difficulty_after}`;
        if (o.unlocked) extra += " · unlocked group by";
      }
      $("out").innerHTML = `
        <div class="verdict ok"><span class="sym">✓</span><span>correct</span><span class="extra">${extra}</span></div>
        <div id="ai-slot"></div>
        <div class="next-hint"><button id="next-inline">next level</button><kbd>↵</kbd></div>
        ${table}`;
      $("next-inline").onclick = nextLevel;
      ta().blur();
      if (S.status.ai_feedback) {
        api("pass_tip", { sql }).then((r) => {
          if (r.lesson && Object.keys(r.lesson).length && $("ai-slot")) $("ai-slot").innerHTML = lessonHTML(r.lesson);
        }).catch(() => {});
      }
    } else {
      $("term").classList.remove("ok");
      shake();
      $("out").innerHTML = `
        <div class="verdict no"><span class="sym">✗</span><span>${esc(v.message)}</span></div>
        ${v.tip ? `<div class="tip">${esc(v.tip)}</div>` : ""}
        ${S.status.ai_feedback ? `<div class="ai loading" id="ai-line"><span class="tag">AI</span><span class="txt">…</span></div>` : ""}
        ${diffHTML(v)}
        ${table}`;
      if (S.status.ai_feedback) {
        api("tutor", { sql }).then((r) => {
          const el = $("ai-line");
          if (!el || lastSQL !== sql) return;
          if (r.lesson && Object.keys(r.lesson).length) el.outerHTML = lessonHTML(r.lesson); else el.remove();
        }).catch(() => $("ai-line")?.remove());
      }
    }
    revealOut();
  } catch (e) { toast(e.message, { ms: 5000 }); }
  finally { $("run-btn").disabled = false; }
}

function revealOut() {
  const r = $("out").getBoundingClientRect();
  if (r.top > window.innerHeight - 120) window.scrollBy({ top: r.top - window.innerHeight / 3, behavior: "smooth" });
}

async function tryRun() {
  const sql = ta().value.trim();
  if (!sql) return;
  remember(sql);
  try {
    const res = await api("run", { sql });
    setTimeout(revealOut, 0);
    $("out").innerHTML = `<div class="verdict info"><span class="sym">›</span><span>tried</span><span class="extra">not graded · ${MOD}↵ to ${mode === "exam" ? "save" : "answer"}</span></div>${resultHTML(res)}`;
  } catch (e) { toast(e.message, { ms: 5000 }); }
}

async function nextLevel() {
  if (mode !== "practice") return;
  const slow = setTimeout(() => toast("Preparing your next level", { ms: 0, spin: true }), 500);
  try {
    S = await api("next", { topic: null });
    passed = false;
    $("term").classList.remove("ok");
    $("out").innerHTML = "";
    setEditor("");
    renderAll();
    ta().focus();
  } catch (e) { toast(e.message, { ms: 5000 }); }
  finally { clearTimeout(slow); untoast(); }
}

async function hint() {
  if (mode !== "practice") return;
  const h = await api("hint", {});
  if (h.text) { S.level.hints_used.push(h.text); renderPractice(); }
}

function giveUp() {
  if (mode !== "practice") return;
  const go = async () => {
    const a = await api("answer", {});
    S.status = a.status; renderBar(); renderRail();
    passed = true;
    $("out").innerHTML = `
      <div class="verdict info"><span class="sym">→</span><span>answer</span></div>
      <pre class="answer">${esc(a.answer)}</pre>
      <div class="tip">${esc(a.explain)}</div>
      <div class="next-hint"><button id="next-inline">next level</button><kbd>↵</kbd></div>
      ${psqlTable(a.columns, a.rows, false, a.numeric)}`;
    $("next-inline").onclick = nextLevel;
    ta().blur();
  };
  if (S.level.finished) go();
  else confirmSheet("Show the answer?", "This counts as a miss for this topic.", "Show answer", go);
}

// ------------------------------------------------------------------ exam
function renderExam() {
  const ex = S.exam, q = ex.questions[examIndex];
  $("exam-dots").innerHTML = ex.questions.map((qq, i) => {
    const done = (examDrafts[i] ?? qq.answer_sql ?? "").trim();
    return `<button class="${i === examIndex ? "cur" : ""} ${done ? "done" : ""}" data-i="${i}">${i + 1}</button>`;
  }).join("");
  $("exam-dots").querySelectorAll("button").forEach((b) => (b.onclick = () => examGo(+b.dataset.i)));
  renderQuestion(q, `question ${examIndex + 1} of ${ex.questions.length} · ${q.points} pts`);
  $("hints").innerHTML = "";
  setEditor(examDrafts[examIndex] ?? q.answer_sql ?? "");
  $("out").innerHTML = "";
  renderKeys();
  startTimer();
}

function stashDraft() { if (mode === "exam") examDrafts[examIndex] = ta().value; }

function examGo(i) {
  const n = S.exam.questions.length;
  if (i < 0 || i >= n) return;
  stashDraft();
  const sql = (examDrafts[examIndex] || "").trim();
  if (sql && sql !== (S.exam.questions[examIndex].answer_sql || "").trim()) {
    S.exam.questions[examIndex].answer_sql = sql;
    api("exam/answer", { index: examIndex, sql }).catch(() => {});
  }
  examIndex = i;
  renderExam();
  ta().focus();
}

async function examSave() {
  const sql = ta().value;
  if (!sql.trim()) return;
  examDrafts[examIndex] = sql;
  const res = await api("exam/answer", { index: examIndex, sql });
  S.exam.questions[examIndex].answer_sql = sql;
  $("out").innerHTML = `<div class="verdict ok"><span class="sym">●</span><span>saved</span><span class="extra">graded when you submit</span></div>${resultHTML(res)}`;
  $("exam-dots").children[examIndex].classList.add("done");
}

function startTimer() {
  clearInterval(timer);
  const ex = S.exam;
  if (!ex || ex.remaining == null) { $("exam-timer").textContent = ""; return; }
  const end = Date.now() + ex.remaining * 1000;
  const tick = () => {
    const left = Math.max(0, Math.round((end - Date.now()) / 1000));
    $("exam-timer").textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
    $("exam-timer").classList.toggle("low", left < 300);
    if (left === 0) { clearInterval(timer); toast("Time's up"); submitExam(true); }
  };
  tick();
  timer = setInterval(tick, 1000);
}

function startExam() {
  let minutes = null;
  sheet({
    html: `<h3>Mock exam</h3>
      <p>Ten questions in this world, mixed like the HOA: three at level 3, five at level 4, two at level 5.
      No hints. Revise answers until you submit.</p>
      <div class="seg" id="seg">${[["none", null], ["30 min", 30], ["45 min", 45], ["60 min", 60], ["90 min", 90]]
        .map(([l, v]) => `<button data-v="${v ?? ""}" class="${v === null ? "on" : ""}">${l}</button>`).join("")}</div>`,
    ok: "Start",
    onOpen: () => $("seg").querySelectorAll("button").forEach((b) => (b.onclick = () => {
      $("seg").querySelectorAll("button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      minutes = b.dataset.v ? +b.dataset.v : null;
    })),
    onOk: async () => {
      toast("Building your exam", { ms: 0, spin: true });
      try {
        S = await api("exam/start", { minutes });
        mode = "exam"; examIndex = 0; examDrafts = {};
        renderAll(); ta().focus();
      } catch (e) { toast(e.message, { ms: 5000 }); return; }
      untoast();
    },
  });
}

function submitExam(force) {
  stashDraft();
  const go = async () => {
    // flush unsaved drafts
    for (const [i, sql] of Object.entries(examDrafts)) {
      if (sql.trim() && sql.trim() !== (S.exam.questions[i].answer_sql || "").trim()) {
        await api("exam/answer", { index: +i, sql }).catch(() => {});
        S.exam.questions[i].answer_sql = sql;
      }
    }
    clearInterval(timer);
    toast(S.status.ai ? "Grading and writing feedback" : "Grading", { ms: 0, spin: true });
    try {
      const out = await api("exam/submit", {});
      S = out.state;
      mode = "report";
      renderAll();
      showReport(out.summary);
    } catch (e) { toast(e.message, { ms: 5000 }); return; }
    untoast();
  };
  const blank = S.exam.questions.filter((q, i) => !((examDrafts[i] ?? q.answer_sql ?? "").trim())).length;
  if (force || !blank) go();
  else confirmSheet("Submit exam?", `${blank} question${blank === 1 ? " is" : "s are"} still blank.`, "Submit", go);
}

function showReport(s) {
  const pct = s.total ? Math.round((100 * s.score) / s.total) : 0;
  const m = Math.floor(s.seconds / 60), sec = s.seconds % 60;
  $("report").innerHTML = `
    <h2>${s.correct} of ${s.count} correct</h2>
    <div class="sub">${s.score} / ${s.total} pts · ${pct}% · ${m}m ${String(sec).padStart(2, "0")}s</div>
    ${s.results.map((r) => `
      <div class="ritem">
        <div class="rm"><span class="${r.passed ? "ok" : "no"}">${r.passed ? "✓" : "✗"}</span>
          <span>question ${r.index + 1} · level ${r.difficulty} · ${esc(r.topic)} · ${r.points} pts</span></div>
        <p class="rq">${esc(r.question)}</p>
        ${r.passed ? "" : `
          <div class="lbl">Your answer</div><pre>${esc(r.sql || "(blank)")}</pre>
          <div class="msg">${esc(r.message)}</div>
          ${r.ai_comment ? `<div class="ai"><span class="tag">AI</span><span class="txt">${esc(r.ai_comment)}</span></div>`
            : r.tip ? `<div class="why">${esc(r.tip)}</div>` : ""}
          <div class="lbl">Answer</div><pre>${esc(r.answer)}</pre>
          <div class="why">${esc(r.explain)}</div>`}
      </div>`).join("")}
    <div class="next-hint" style="margin-left:0"><button id="report-back">back to practice</button><kbd>↵</kbd></div>`;
  $("report-back").onclick = backToPractice;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function backToPractice() {
  mode = "practice";
  $("out").innerHTML = ""; setEditor("");
  renderAll();
  ta().focus();
}

function aiSettings() { settingsSheet(); }

function settingsSheet() {
  const st = S.status;
  const row = (key, title, desc, disabled) => `
    <div class="toggle-row ${disabled ? "disabled" : ""}" data-key="${key}">
      <span class="t">${title}</span><button class="switch ${st[key] ? "on" : ""}" aria-label="${title}" ${disabled ? "disabled" : ""}></button>
      <span class="d">${desc}</span>
    </div>`;
  const aiNote = st.ai ? "" : `<p class="set-note">Add <code>OPENAI_API_KEY=…</code> to <code>.env</code> and restart to enable AI.</p>`;
  sheet({
    html: `<h3>Settings</h3>
      <div class="set-sec">Practice</div>
      ${row("groupby", "GROUP BY / HAVING", "Include this topic. Turn it off if it isn't on your exam.")}
      ${row("show_expected", "Expected output", "Show the expected result under each question.")}
      ${row("sticky_question", "Pin the question", "Keep the question visible while you scroll.")}
      <div class="set-sec">AI</div>
      ${row("ai_feedback", "Feedback", "Mini-lessons when you're wrong or right. About $0.001 each.", !st.ai)}
      ${row("ai_levels", "AI-written levels", "New exam-style levels made in the background. About $0.01 each.", !st.ai)}
      ${aiNote}
      <p class="set-note">${S.models ? `models · ${esc(S.models.generate)} / ${esc(S.models.feedback)}` : ""}</p>`,
    ok: "Done", cancel: null,
    onOpen: () => document.querySelectorAll(".toggle-row:not(.disabled)").forEach((r) => {
      r.querySelector(".switch").onclick = async (e) => {
        const btn = e.currentTarget, on = !btn.classList.contains("on");
        btn.classList.toggle("on", on);
        const key = r.dataset.key;
        const wasGroupby = key === "groupby" && !on && S.level && S.level.topic === "groupby";
        S = await api("setting", { key, on });
        renderBar(); renderRail();
        if (wasGroupby || key === "show_expected" || key === "sticky_question") {
          const keep = ta().value;
          renderAll();
          if (mode === "practice" && !wasGroupby) setEditor(keep);
          if (wasGroupby) { $("out").innerHTML = ""; setEditor(""); toast("Swapped out the GROUP BY level"); }
        }
      };
    }),
  });
}

// ------------------------------------------------------------------ wiring
function wire() {
  const t = ta();
  t.addEventListener("input", syncEditor);
  t.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); e.shiftKey ? tryRun() : run(); return; }
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown") && mode === "practice") {
      e.preventDefault(); historyStep(e.key === "ArrowUp" ? 1 : -1); return;
    }
    if (e.key === "Tab") {
      e.preventDefault();
      insert("    ");
    }
  });
  window.addEventListener("resize", syncEditor);

  document.addEventListener("keydown", (e) => {
    if (!$("sheet").hidden) return;
    if (e.altKey && !e.metaKey && !e.ctrlKey) {
      const map = mode === "exam"
        ? { ArrowLeft: "prev", ArrowRight: "next" }
        : { KeyH: "hint", KeyA: "answer", KeyS: "skip" };
      const a = map[e.code];
      if (a) { e.preventDefault(); act(a); return; }
    }
    if (e.key === "Enter" && document.activeElement !== t && !e.metaKey && !e.ctrlKey) {
      if (mode === "report") { e.preventDefault(); backToPractice(); }
      else if (mode === "practice" && passed) { e.preventDefault(); nextLevel(); }
    }
    if (e.key === "/" && document.activeElement !== t && mode !== "report") { e.preventDefault(); t.focus(); }
  });

  $("run-btn").onclick = run;
  $("qb-text").onclick = () => $("qb-text").classList.toggle("full");
  $("qb-exp").onclick = () => {
    qbarExp = !qbExpOn();
    const lv = mode === "exam" ? S.exam.questions[examIndex] : S.level;
    $("qb-exp").classList.toggle("on", qbarExp);
    $("qb-expected").hidden = !(lv.expected && qbarExp);
    if (lv.expected && qbarExp) $("qb-expected").innerHTML = psqlTable(lv.expected.columns, lv.expected.rows, false, lv.expected.numeric);
  };
  $("qb-close").onclick = async () => {
    S = await api("setting", { key: "sticky_question", on: false });
    updateQbar();
    renderAll();
  };
  $("try-btn").onclick = tryRun;
  $("ai-dot").onclick = settingsSheet;
  $("settings-btn").onclick = settingsSheet;
  $("world").onchange = async (e) => {
    toast("Switching world", { ms: 0, spin: true });
    try {
      S = await api("world", { slug: e.target.value });
      passed = false; $("out").innerHTML = ""; setEditor(""); $("term").classList.remove("ok");
      $("schema").innerHTML = "";
      renderAll();
    } finally { untoast(); }
  };
  $("topic").onchange = async (e) => {
    S = await api("topic", { topic: e.target.value || null });
    if (e.target.value) { passed = false; $("out").innerHTML = ""; setEditor(""); $("term").classList.remove("ok"); }
    renderAll();
  };
  $("exam-btn").onclick = startExam;
  $("exam-submit").onclick = () => submitExam(false);
  $("exam-quit").onclick = () => confirmSheet("Abandon exam?", "Your answers won't be graded.", "Abandon", async () => {
    clearInterval(timer);
    S = await api("exam/quit", {});
    mode = "practice"; $("out").innerHTML = ""; setEditor("");
    renderAll();
  });
  $("newworld-btn").onclick = () => sheet({
    html: `<h3>New world</h3><p>Describe a theme, or leave it blank for a surprise. The AI designs the tables
      and data, then psqlay checks them before you play. Takes a minute or two.</p>
      <input id="theme" placeholder="a coffee shop, a football league, a zoo…" autocomplete="off">`,
    ok: "Create",
    onOpen: () => setTimeout(() => $("theme").focus(), 50),
    onOk: async () => {
      const theme = $("theme").value.trim() || null;
      toast("Designing your world", { ms: 0, spin: true });
      try {
        const out = await api("newworld", { theme });
        S = out.state; renderAll();
        toast(`${out.world.emoji} ${out.world.name} is ready. Pick it from the world menu.`, { ms: 6000 });
      } catch (e) { toast("Couldn't build a world: " + e.message, { ms: 7000 }); }
    },
  });
}

wire();
refresh().then(() => ta().focus()).catch((e) => toast(e.message, { ms: 8000 }));
