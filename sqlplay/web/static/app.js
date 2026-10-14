// psqlay web front end (no framework).
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let S = null;           // last /api/state
let examIndex = 0;
let timerHandle = null;
let lastSQL = "";

async function api(path, body) {
  const opts = body === undefined
    ? { method: "GET" }
    : { method: "POST", headers: { "Content-Type": "application/json", "X-Psqlay": "1" }, body: JSON.stringify(body) };
  const r = await fetch("/api/" + path, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.statusText);
  return data;
}

function toast(msg, ms = 3000) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.h);
  toast.h = setTimeout(() => (t.hidden = true), ms);
}

function modal(html, onClose) {
  $("modal-body").innerHTML = html;
  $("modal-close").textContent = "Got it";
  $("modal").hidden = false;
  $("modal-close").onclick = () => { $("modal").hidden = true; onClose && onClose(); };
}

// ------------------------------------------------------------------ rendering
function renderTable(res, el) {
  if (!res) { el.innerHTML = ""; return; }
  if (res.error) { el.innerHTML = `<pre class="err">${esc(res.error)}</pre>`; return; }
  const head = res.columns.map((c) => `<th>${esc(c)}</th>`).join("");
  const body = res.rows.map((r) => "<tr>" + r.map((v) => {
    if (v === null) return '<td class="null">NULL</td>';
    const num = typeof v === "number";
    return `<td class="${num ? "num" : ""}">${esc(v)}</td>`;
  }).join("") + "</tr>").join("");
  const n = res.rows.length;
  el.innerHTML = `<table class="grid"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
    <div class="rowcount">(${n} row${n === 1 ? "" : "s"}${res.truncated ? ", showing first 500" : ""})</div>`;
}

function renderTop() {
  const st = S.status;
  $("score").textContent = st.score;
  $("streak").textContent = "🔥 " + st.streak;
  const b = $("ai-badge");
  b.textContent = st.ai ? "🤖 AI on" : "AI off (no key)";
  b.className = "badge" + (st.ai ? " on" : "");
  b.title = S.models ? `generate: ${S.models.generate} · feedback: ${S.models.feedback}` : "Add OPENAI_API_KEY to .env";
  $("newworld-btn").hidden = !st.ai;

  $("world").innerHTML = S.worlds.map((w) =>
    `<option value="${esc(w.slug)}" ${w.slug === st.world.slug ? "selected" : ""}>${esc(w.emoji)} ${esc(w.name)}${w.source === "ai" ? " 🤖" : ""}</option>`
  ).join("");
  const opts = [`<option value="">🎲 Mix (adaptive)</option>`].concat(
    st.topics.filter((t) => t.unlocked).map((t) =>
      `<option value="${t.topic}" ${st.locked === t.topic ? "selected" : ""}>${esc(t.name)}</option>`)
  );
  $("topic").innerHTML = opts.join("");
}

function renderSidebar() {
  $("schema").innerHTML = S.schema.map((t) => `
    <details class="tbl" open>
      <summary>${esc(t.table)} <span class="rows">(${t.rows})</span></summary>
      <div class="cols">${t.columns.map((c) => `
        <div data-col="${esc(c.name)}" title="click to insert">
          <span>${esc(c.name)}</span><span class="type">${esc(c.type)}</span>
          <span class="key">${c.pk ? "PK" : c.fk ? "→ " + esc(c.fk) : ""}</span>
        </div>`).join("")}</div>
    </details>`).join("");
  $("schema").querySelectorAll("[data-col]").forEach((d) => d.onclick = () => insertText(d.dataset.col));
  $("joinmap").textContent = S.join_map || "";
  $("notes").textContent = S.notes || "";
  $("levels").innerHTML = S.status.topics.map((t) => `
    <div class="lvl ${t.unlocked ? "" : "locked"}" title="${t.unlocked ? "" : "Unlocks after 3 aggregate passes"}">
      <span>${esc(t.name)}</span><span class="muted">L${t.difficulty} · ${t.passed}/${t.attempted}</span>
      <div class="bar"><i style="width:${t.difficulty * 20}%"></i></div>
    </div>`).join("");
}

function reqs(lv, el) {
  const bits = [];
  if (lv.columns && lv.columns.length) bits.push("Columns: " + lv.columns.map((c) => `<code>"${esc(c)}"</code>`).join(" "));
  if (lv.ordered && lv.order_note) bits.push("Sort: <code>" + esc(lv.order_note) + "</code>");
  el.innerHTML = bits.join(" &nbsp;·&nbsp; ");
}

function renderLevel() {
  const lv = S.level;
  if (!lv) return;
  $("q-level").textContent = "Level " + lv.difficulty;
  $("q-topic").textContent = lv.topic_name;
  $("q-source").textContent = { builtin: "", generated: "· generated", ai: "· 🤖 AI" }[lv.source] || "";
  $("q-points").textContent = lv.points + " pts";
  $("q-text").textContent = lv.question;
  reqs(lv, $("q-reqs"));
  $("hints").innerHTML = lv.hints_used.map((h, i) => `<div class="hint">💡 <b>Hint ${i + 1}:</b> ${esc(h)}</div>`).join("");
  $("hint-btn").disabled = lv.hints_used.length >= lv.hint_count;
  if (lv.groupby_intro) modal(`<h3>🆕 GROUP BY / HAVING unlocked</h3><pre>${esc(lv.groupby_intro)}</pre>`);
}

function renderAll() {
  renderTop();
  renderSidebar();
  const inExam = !!S.exam;
  $("practice").hidden = inExam;
  $("exam").hidden = !inExam;
  $("exam-btn").hidden = inExam;
  if (inExam) renderExam(); else { $("exam-report").hidden = true; renderLevel(); }
}

async function refresh() {
  S = await api("state");
  renderAll();
}

function insertText(t) {
  const ta = S.exam ? $("exam-sql") : $("sql");
  const s = ta.selectionStart, e = ta.selectionEnd;
  ta.value = ta.value.slice(0, s) + t + ta.value.slice(e);
  ta.selectionStart = ta.selectionEnd = s + t.length;
  ta.focus();
}

// ------------------------------------------------------------------ practice
function clearFeedback() { $("feedback").innerHTML = ""; $("result").innerHTML = ""; }

async function runAndGrade() {
  const sql = $("sql").value.trim();
  if (!sql) return;
  lastSQL = sql;
  $("run-btn").disabled = true;
  try {
    const out = await api("submit", { sql });
    if (out.broken) { toast(out.message, 5000); return; }
    const v = out.verdict;
    renderTable(v.result, $("result"));
    S.status = out.status;
    renderTop(); renderSidebar();
    const fb = $("feedback");
    if (v.passed) {
      let head = "✓ Correct!";
      let extra = "";
      if (out.first_pass && out.outcome) {
        const o = out.outcome;
        head = `✓ PASS! +${o.points} pts`;
        if (o.difficulty_after > o.difficulty_before) extra += ` &nbsp;⬆ Level ${o.difficulty_after} unlocked in ${esc(S.level.topic_name)}`;
        if (o.unlocked) extra += " &nbsp;🆕 New topic: GROUP BY / HAVING";
      }
      fb.innerHTML = `<div class="feedback pass"><div class="head">${head}${extra}</div>
        <div id="ai-line"></div>
        <div class="next"><button class="primary" id="next-inline">Next level →</button></div></div>`;
      $("next-inline").onclick = nextLevel;
      if (S.status.ai) {
        api("pass_tip", { sql }).then((r) => { if (r.text) $("ai-line").innerHTML = `<div class="ai">🤖 ${esc(r.text)}</div>`; }).catch(() => {});
      }
    } else {
      fb.innerHTML = `<div class="feedback fail"><div class="head">✗ ${esc(v.message)}</div>
        ${v.tip ? `<div class="tip">${esc(v.tip)}</div>` : ""}
        ${S.status.ai ? '<div class="ai loading spin" id="ai-line">🤖 thinking</div>' : ""}</div>`;
      if (S.status.ai) {
        api("tutor", { sql }).then((r) => {
          const el = $("ai-line");
          if (!el || lastSQL !== sql) return;
          if (r.text) { el.className = "ai"; el.textContent = "🤖 " + r.text; } else el.remove();
        }).catch(() => { const el = $("ai-line"); el && el.remove(); });
      }
    }
  } catch (e) { toast(e.message, 5000); }
  finally { $("run-btn").disabled = false; }
}

async function nextLevel() {
  $("next-btn").disabled = true;
  const t = setTimeout(() => toast("Finding your next level…", 20000), 600);
  try {
    S = await api("next", { topic: null });
    clearFeedback();
    $("sql").value = "";
    renderAll();
  } catch (e) { toast(e.message, 5000); }
  finally { clearTimeout(t); $("toast").hidden = true; $("next-btn").disabled = false; }
}

async function hint() {
  const h = await api("hint", {});
  if (h.text) { S.level.hints_used.push(h.text); renderLevel(); }
}

async function giveUp() {
  if (!S.level.finished && !confirm("Give up and see the answer? (Counts as a miss.)")) return;
  const a = await api("answer", {});
  S.status = a.status; renderTop(); renderSidebar();
  $("feedback").innerHTML = `<div class="feedback fail answer"><div class="head">Answer</div>
    <pre>${esc(a.answer)}</pre><div class="tip">${esc(a.explain)}</div>
    <div class="next"><button class="primary" id="next-inline">Next level →</button></div></div>`;
  $("next-inline").onclick = nextLevel;
  renderTable({ columns: a.columns, rows: a.rows }, $("result"));
}

// ------------------------------------------------------------------ exam
function renderExam() {
  const ex = S.exam;
  const q = ex.questions[examIndex];
  $("exam-nav").innerHTML = ex.questions.map((qq, i) =>
    `<button class="${i === examIndex ? "cur" : ""} ${qq.answer_sql ? "done" : ""}" data-i="${i}">${i + 1}</button>`).join("");
  $("exam-nav").querySelectorAll("button").forEach((b) => b.onclick = () => { saveExamDraft(); examIndex = +b.dataset.i; renderExam(); });
  $("eq-level").textContent = "Level " + q.difficulty;
  $("eq-num").textContent = `Question ${examIndex + 1} of ${ex.questions.length}`;
  $("eq-points").textContent = q.points + " pts";
  $("eq-text").textContent = q.question;
  reqs(q, $("eq-reqs"));
  $("exam-sql").value = q.answer_sql || "";
  $("exam-saved").textContent = q.answer_sql ? "answer saved" : "";
  $("exam-result").innerHTML = "";
  startTimer();
}

function saveExamDraft() {
  if (!S.exam) return;
  const q = S.exam.questions[examIndex];
  const v = $("exam-sql").value;
  if (v.trim() && v !== q.answer_sql) { q.answer_sql = v; api("exam/answer", { index: examIndex, sql: v }).catch(() => {}); }
}

async function examSave() {
  const sql = $("exam-sql").value;
  if (!sql.trim()) return;
  const res = await api("exam/answer", { index: examIndex, sql });
  S.exam.questions[examIndex].answer_sql = sql;
  $("exam-saved").textContent = "answer saved ✓";
  renderTable(res, $("exam-result"));
  $("exam-nav").querySelectorAll("button")[examIndex].classList.add("done");
}

function startTimer() {
  clearInterval(timerHandle);
  const ex = S.exam;
  if (!ex || ex.remaining === null || ex.remaining === undefined) { $("exam-timer").textContent = ""; return; }
  const end = Date.now() + ex.remaining * 1000;
  const tick = () => {
    const left = Math.max(0, Math.round((end - Date.now()) / 1000));
    $("exam-timer").textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
    if (left === 0) { clearInterval(timerHandle); toast("⏰ Time's up! Submitting…"); submitExam(true); }
  };
  tick();
  timerHandle = setInterval(tick, 1000);
}

async function startExam() {
  const html = `<h3>📝 Mock exam</h3>
    <p>10 questions in this world, mixed like the HOA: ~3 at level 3, ~5 at level 4, ~2 at level 5.
    No hints. You can revise answers until you submit.</p>
    <label>Time limit in minutes (blank = none): <input id="exam-min" type="number" min="5" max="240" placeholder="e.g. 45"></label>`;
  modal(html, async () => {
    const m = parseInt($("exam-min").value, 10);
    try {
      toast("Building your exam…", 15000);
      S = await api("exam/start", { minutes: Number.isFinite(m) ? m : null });
      $("toast").hidden = true;
      examIndex = 0;
      renderAll();
    } catch (e) { toast(e.message, 5000); }
  });
  $("modal-close").textContent = "Start exam";
}

async function submitExam(force) {
  saveExamDraft();
  const blank = S.exam.questions.filter((q) => !q.answer_sql || !q.answer_sql.trim()).length;
  if (!force && blank && !confirm(`${blank} question(s) are blank. Submit anyway?`)) return;
  clearInterval(timerHandle);
  $("exam-submit").disabled = true;
  toast(S.status.ai ? "Grading and writing comments…" : "Grading…", 60000);
  try {
    const out = await api("exam/submit", {});
    $("toast").hidden = true;
    S = out.state;
    renderAll();
    showReport(out.summary);
  } catch (e) { toast(e.message, 5000); }
  finally { $("exam-submit").disabled = false; }
}

function showReport(s) {
  const pct = s.total ? Math.round((100 * s.score) / s.total) : 0;
  const mins = Math.floor(s.seconds / 60), secs = s.seconds % 60;
  const items = s.results.map((r) => `
    <div class="report-item ${r.passed ? "ok" : "no"}">
      <b>${r.passed ? "✓" : "✗"} Q${r.index + 1}</b> <span class="muted">L${r.difficulty} · ${r.points} pts · ${esc(r.topic)}</span>
      <div>${esc(r.question)}</div>
      ${r.passed ? "" : `
        <div class="muted">Your answer:</div><pre>${esc(r.sql || "(blank)")}</pre>
        <div style="color:var(--bad)">${esc(r.message)}</div>
        ${r.ai_comment ? `<div class="ai" style="color:#9fd0ff">🤖 ${esc(r.ai_comment)}</div>` : r.tip ? `<div>${esc(r.tip)}</div>` : ""}
        <div class="muted">Answer:</div><pre>${esc(r.answer)}</pre>
        <div class="muted">${esc(r.explain)}</div>`}
    </div>`).join("");
  const el = $("exam-report");
  el.innerHTML = `<div class="card"><h2>📝 Exam results: ${s.correct}/${s.count} correct · ${s.score}/${s.total} pts (${pct}%)</h2>
    <div class="muted">Time: ${mins}m ${secs}s</div>${items}
    <div class="actions"><div class="spacer"></div><button class="primary" id="report-close">Back to practice</button></div></div>`;
  el.hidden = false;
  $("practice").hidden = true;
  $("report-close").onclick = () => { el.hidden = true; $("practice").hidden = false; };
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------------ wiring
function editorKeys(ta, onRun) {
  ta.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); onRun(); }
    else if (e.key === "Tab") {
      e.preventDefault();
      const s = ta.selectionStart;
      ta.value = ta.value.slice(0, s) + "    " + ta.value.slice(ta.selectionEnd);
      ta.selectionStart = ta.selectionEnd = s + 4;
    }
  });
}

function wire() {
  editorKeys($("sql"), runAndGrade);
  editorKeys($("exam-sql"), examSave);
  $("run-btn").onclick = runAndGrade;
  $("hint-btn").onclick = hint;
  $("answer-btn").onclick = giveUp;
  $("next-btn").onclick = nextLevel;
  $("world").onchange = async (e) => {
    toast("Switching world…");
    S = await api("world", { slug: e.target.value });
    clearFeedback(); $("sql").value = ""; renderAll();
  };
  $("topic").onchange = async (e) => {
    S = await api("topic", { topic: e.target.value || null });
    if (e.target.value) { clearFeedback(); $("sql").value = ""; }
    renderAll();
  };
  $("exam-btn").onclick = startExam;
  $("exam-save").onclick = examSave;
  $("exam-prev").onclick = () => { saveExamDraft(); examIndex = Math.max(0, examIndex - 1); renderExam(); };
  $("exam-next").onclick = () => { saveExamDraft(); examIndex = Math.min(S.exam.questions.length - 1, examIndex + 1); renderExam(); };
  $("exam-submit").onclick = () => submitExam(false);
  $("exam-quit").onclick = async () => {
    if (!confirm("Abandon this exam?")) return;
    clearInterval(timerHandle);
    S = await api("exam/quit", {});
    renderAll();
  };
  $("newworld-btn").onclick = () => {
    modal(`<h3>✨ New AI world</h3><p>Describe a theme (or leave blank for a surprise). Takes about a minute.</p>
      <input id="theme" placeholder="e.g. a coffee shop, a football league, a zoo">`, async () => {
      const theme = $("theme").value.trim() || null;
      toast("🤖 Designing your world… (about a minute)", 120000);
      try {
        const out = await api("newworld", { theme });
        S = out.state;
        $("toast").hidden = true;
        renderAll();
        toast(`New world: ${out.world.emoji} ${out.world.name}. Pick it from the World menu.`, 6000);
      } catch (e) { toast("Couldn't build a world: " + e.message, 7000); }
    });
    $("modal-close").textContent = "Create";
  };
}

wire();
refresh().catch((e) => toast(e.message, 8000));
