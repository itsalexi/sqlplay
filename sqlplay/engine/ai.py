"""Optional AI features (OpenAI). Everything here is a no-op without a key.

All provider calls live in this file: swap providers by editing `_call`.
AI output is untrusted: worlds go through the validator, levels through
generator.validate_spec, and nothing here ever executes SQL itself.
"""

from __future__ import annotations

import json
import re

from . import config

GEN_MODEL_DEFAULT = "gpt-6.1-sol"
FEEDBACK_MODEL_DEFAULT = "gpt-6.1-sol"


class AIError(RuntimeError):
    pass


def available() -> bool:
    if not config.get("OPENAI_API_KEY"):
        return False
    try:
        import openai  # noqa: F401
    except ImportError:
        return False
    return True


def _client():
    import openai

    return openai.OpenAI(api_key=config.get("OPENAI_API_KEY"), timeout=180, max_retries=1)


def _call(model: str, effort: str, instructions: str, prompt: str, json_out: bool) -> str:
    if not available():
        raise AIError("No OpenAI key configured")
    kwargs = dict(model=model, reasoning={"effort": effort}, instructions=instructions, input=prompt)
    if json_out:
        kwargs["text"] = {"format": {"type": "json_object"}}
    try:
        resp = _client().responses.create(**kwargs)
    except Exception as e:  # network, auth, quota, bad model...
        raise AIError(f"{type(e).__name__}: {str(e)[:200]}") from e
    return resp.output_text or ""


def _json(model: str, effort: str, instructions: str, prompt: str) -> dict:
    text = _call(model, effort, instructions, prompt + "\n\nRespond with a single JSON object.", json_out=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise AIError("Model did not return JSON")


def gen_model() -> str:
    return config.get("OPENAI_GEN_MODEL", GEN_MODEL_DEFAULT)


def feedback_model() -> str:
    return config.get("OPENAI_FEEDBACK_MODEL", FEEDBACK_MODEL_DEFAULT)


# ------------------------------------------------------------------ feedback
TUTOR_RULES = """You are a patient SQL teacher for a beginner practising PostgreSQL for a hands-on exam.
The student knows: SELECT/WHERE, AS labels, CONCAT, ORDER BY, DISTINCT, MAX/MIN/AVG/COUNT,
subqueries, JOIN ... ON chains, self-joins, LEFT JOIN ... IS NULL, and is learning GROUP BY/HAVING.
TEACH, don't just tell: name the underlying idea, explain WHY it works the way it does (the mental
model), and give the student something to try so they discover it themselves.
Rules:
- Plain English, friendly, short. Every field is ONE or TWO sentences at most.
- Examples must use DIFFERENT tables/columns/values than the question (a generic toy table like
  students(name, grade, city) is ideal) so they illustrate the idea without solving the task.
- Any JOIN style (ON, WHERE equijoin, NATURAL JOIN) is fine if it gives the right rows.
- No markdown, no headings, no code fences. SQL inside example fields is plain one-line text."""

LESSON_KEYS = ("concept", "explain", "example", "nudge", "try")


def _lesson(d: dict) -> dict:
    """Keep only short string fields we know how to show."""
    out = {}
    for k in LESSON_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = " ".join(v.split())[:400]
    return out


def tutor_feedback(
    question: str, user_sql: str, problem: str, rule_tip: str, answer_sql: str,
    expected_preview: str, user_preview: str,
) -> dict:
    """A short lesson about the student's main mistake. Never reveals the answer."""
    prompt = (
        f"QUESTION:\n{question}\n\nSTUDENT QUERY:\n{user_sql}\n\nGRADER SAYS: {problem}\n"
        f"RULE-BASED TIP ALREADY SHOWN: {rule_tip or '(none)'}\n\n"
        f"STUDENT RESULT (sample):\n{user_preview}\n\nEXPECTED RESULT (sample):\n{expected_preview}\n\n"
        f"REFERENCE ANSWER (secret, NEVER reveal or paraphrase it):\n{answer_sql}\n\n"
        "Find the ONE most important misunderstanding and teach it. Return JSON with:\n"
        '  "concept": 2-5 word name of the idea (e.g. "LEFT JOIN keeps unmatched rows"),\n'
        '  "explain": the mental model: why SQL behaves this way (1-2 sentences, general, not their query),\n'
        '  "example": a tiny one-line SQL on a DIFFERENT toy table showing the idea, or "" if not useful,\n'
        '  "nudge": what to reconsider in THEIR query: name the clause/condition, but don\'t give the fix,\n'
        '  "try": a question or small experiment for them (e.g. run part of the query with \\g and compare).\n'
        "Don't spell out the values, dates, or complete clauses they need."
    )
    return _lesson(_json(feedback_model(), "low", TUTOR_RULES, prompt))


def pass_tip(question: str, user_sql: str, answer_sql: str) -> dict:
    """After a correct answer: teach one transferable idea (a cleaner form, an alternative, a pitfall avoided)."""
    prompt = (
        f"QUESTION:\n{question}\n\nSTUDENT QUERY (correct!):\n{user_sql}\n\nREFERENCE:\n{answer_sql}\n\n"
        "The student got it right. Teach ONE transferable idea from this query: a cleaner or shorter form, an "
        "alternative style they should recognise on an exam, or a pitfall they avoided and why it matters. "
        "Return JSON with:\n"
        '  "concept": 2-5 word name of the idea,\n'
        '  "explain": why it works / when to use it / when NOT to (1-2 sentences),\n'
        '  "example": a one-line before/after or illustration on a DIFFERENT toy table,\n'
        '  "try": a tiny experiment, e.g. "rewrite your WHERE with IN and run it with \\g: same rows?".\n'
        'If there is genuinely nothing worth teaching, return {"concept": ""}.'
    )
    return _lesson(_json(feedback_model(), "low", TUTOR_RULES, prompt))


def exam_comment(question: str, user_sql: str, verdict: str, answer_sql: str) -> str:
    prompt = (
        f"QUESTION:\n{question}\n\nSTUDENT QUERY:\n{user_sql or '(left blank)'}\n\nRESULT: {verdict}\n\n"
        f"REFERENCE ANSWER:\n{answer_sql}\n\n"
        "This is the end-of-exam review, so you MAY explain the fix now. In 2-3 plain sentences: what "
        "they misunderstood, the idea that fixes it, and how the reference applies it. No markdown."
    )
    return _call(feedback_model(), "low", TUTOR_RULES, prompt, json_out=False).strip()


# ------------------------------------------------------------------ generation
LEVEL_RULES = """You write SQL practice questions for a PostgreSQL hands-on exam (HOA).
Return ONE JSON object with keys: question, columns, ordered, order_note, answer, hints, explain.
- question: plain-English business question that FULLY determines the result: which columns, the
  exact label of each column (if columns given), full-name format "first name, a space, last name",
  whether items appear once, and the sort order if any. Names/titles in the data are CAPITALS.
- columns: list of exact output labels in order, or [] if labels aren't required.
- ordered: true only if the question asks for an order; then ORDER BY output columns with NO ties
  (add a tie-breaker). order_note: short description of the order.
- answer: ONE PostgreSQL SELECT using explicit JOIN ... ON and aliases. ONLY these features:
  SELECT/WHERE/AND/OR/IN/BETWEEN/LIKE, AS labels, CONCAT, ORDER BY, DISTINCT, MAX/MIN/AVG/COUNT/SUM,
  ROUND, subqueries in WHERE (=, >, <, IN, NOT IN), JOIN ... ON chains, self-joins, LEFT JOIN ... IS NULL,
  GROUP BY/HAVING. NOT allowed: subqueries in FROM or SELECT, WITH/CTEs, window functions, CASE, LATERAL,
  UNION, schema names. Keep it short: at most ~10 lines. Must return 1-40 rows on the given data.
  ROUND(AVG(..), 2) when an average is shown, and say "rounded to 2 decimals".
- Keep the question SHORT and natural, like the examples: 1-3 sentences, under 70 words. Labels in
  Title Case with spaces (e.g. "Customer Name"), never snake_case.
- Match the EXAMPLES' style and difficulty closely; they are real exam-style questions.
- hints: exactly 3 strings: concept nudge (no code); skeleton with ____ blanks; near-answer.
- explain: 2-4 sentences for a beginner on why the answer works.
Difficulty scale: 1-2 warm-up single skill; 3 typical HOA (two skills combined, labels, sorting);
4 hardest HOA (3+ skills, lookup subquery inside another, long join chain + aggregate subquery);
5 beyond HOA (nested subqueries, LEFT JOIN with extra filters, computed columns, GROUP BY/HAVING with joins).
Wording must be unambiguous so any correct query style returns the same rows."""

TOPIC_GUIDE = {
    "select": "SELECT with WHERE conditions (AND/OR/IN/comparisons)",
    "shape": "AS labels, CONCAT, ORDER BY, DISTINCT",
    "aggregates": "MAX/MIN/AVG/COUNT, optionally with WHERE",
    "subqueries": "subqueries in WHERE (=, >, IN), lookups, aggregate comparisons",
    "joins": "JOIN ... ON chains across several tables",
    "selfleft": "self-joins and LEFT JOIN ... IS NULL",
    "groupby": "GROUP BY and HAVING (with joins at higher difficulty)",
}


def generate_level(
    schema_text: str, sample_text: str, topic: str, difficulty: int, examples: list[dict], avoid_questions: list[str],
) -> dict:
    ex = "\n\n".join(
        f"EXAMPLE (topic {e['topic']}, difficulty {e['difficulty']}):\nQ: {e['question']}\nA: {e['answer']}"
        for e in examples[:3]
    )
    avoid = "\n".join(f"- {q}" for q in avoid_questions[:15])
    prompt = (
        f"DATABASE SCHEMA:\n{schema_text}\n\nSAMPLE DATA:\n{sample_text}\n\n{ex}\n\n"
        f"Write a NEW question. Topic: {topic} ({TOPIC_GUIDE.get(topic, topic)}). Difficulty: {difficulty}.\n"
        f"Do not repeat these existing questions:\n{avoid or '(none)'}"
    )
    return _json(gen_model(), config.get("OPENAI_LEVEL_EFFORT", "medium"), LEVEL_RULES, prompt)


WORLD_RULES = """You design small themed PostgreSQL practice databases for a beginner preparing for an
SQL hands-on exam modelled on a bookstore database (customer - orders - orderitem - book - publisher,
book - bookauthor - author, customer.referredby -> customer).
Return ONE JSON object with keys: slug, name, emoji, blurb, join_map, notes, schema_sql, data_sql.
- slug: lowercase letters/digits/underscore, 3-20 chars. name: catchy. emoji: one emoji. blurb: 1 sentence.
- join_map: lines like "a -col- b -col- c" plus "t.selfcol -> t.pk".
- notes: data conventions (e.g. names in CAPITALS, categories mixed case).
- schema_sql: ONLY CREATE TABLE statements, 5-8 tables, PRIMARY KEY/REFERENCES/CHECK allowed. No schema
  names, no functions, no SERIAL. numeric(8,2) for money, date for dates, varchar for text.
- data_sql: ONLY INSERT INTO t VALUES (...),(...); plain literals, dates 'YYYY-MM-DD'. 150-400 rows total.
Required shapes: a 4-5 table chain; a link-through (many-to-many) table; a column referencing its own
table; rows with no match (items never used, people with no activity); two money columns per item
(cost and price) for profit questions; a mixed-case category column with 4-6 values; NULLs in a
nullable date column; the same person getting the same item twice in different transactions.
People names and item names in CAPITALS. Insert parents before children (foreign keys)."""


def generate_world(theme: str | None, existing_slugs: list[str]) -> dict:
    prompt = (
        f"Theme: {theme or 'surprise me with a fun, everyday theme'}.\n"
        f"Slugs already used (pick a different one): {', '.join(existing_slugs) or '(none)'}"
    )
    return _json(gen_model(), "high", WORLD_RULES, prompt)
