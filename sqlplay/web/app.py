"""psqlay web: a local FastAPI server for one player, bound to 127.0.0.1."""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sqlplay.engine import ai
from sqlplay.engine.game import Game

STATIC = Path(__file__).resolve().parent / "static"


class SQLBody(BaseModel):
    sql: str


class TopicBody(BaseModel):
    topic: str | None = None


class WorldBody(BaseModel):
    slug: str


class DiffBody(BaseModel):
    topic: str
    difficulty: int


class ThemeBody(BaseModel):
    theme: str | None = None


class ToggleBody(BaseModel):
    on: bool


class SettingBody(BaseModel):
    key: str
    on: bool


class ExamStartBody(BaseModel):
    minutes: int | None = None


class ExamAnswerBody(BaseModel):
    index: int
    sql: str


def result_dict(res) -> dict | None:
    if res is None:
        return None
    return {
        "columns": res.columns,
        "rows": [list(r) for r in res.display],
        "numeric": res.numeric,
        "truncated": res.truncated,
        "error": None if res.ok else res.error.psql_text(res.sql),
    }


def create_app(game: Game, port: int = 8000) -> FastAPI:
    app = FastAPI(title="psqlay", docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.RLock()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Only this machine, and only our own page (custom header forces a CORS preflight,
        # which we never approve, so other websites can't drive the API).
        if request.headers.get("host") not in allowed_hosts:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        if request.url.path.startswith("/api/") and request.method != "GET":
            if request.headers.get("x-psqlay") != "1":
                return JSONResponse({"detail": "missing header"}, status_code=403)
        return await call_next(request)

    def level_payload() -> dict:
        lv = game.current()
        d = lv.public_dict()
        d["hints_used"] = [lv.hints[i] for i in range(game.hints_used)]
        d["finished"] = game.finished
        d["passed"] = game.passed
        d["groupby_intro"] = game.groupby_intro() if game.needs_groupby_intro() else None
        d["expected"] = game.expected(lv)
        d["review"] = game.is_review
        return d

    def exam_payload() -> dict | None:
        ex = game.exam
        if not ex:
            return None
        return {
            "world": ex.world,
            "remaining": ex.remaining,
            "minutes": ex.minutes,
            "questions": [
                {**lv.public_dict(), "answer_sql": ex.answers.get(i, ""), "expected": game.expected(lv)}
                for i, lv in enumerate(ex.levels)
            ],
        }

    def state() -> dict:
        meta = game.world_meta()
        return {
            "status": game.status(),
            "level": None if game.exam else level_payload(),
            "exam": exam_payload(),
            "schema": game.schema(),
            "join_map": meta.get("join_map", ""),
            "notes": meta.get("notes", ""),
            "worlds": game.worlds(),
            "models": {"generate": ai.gen_model(), "feedback": ai.feedback_model()} if game.ai_available() else None,
        }

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/state")
    def get_state():
        with lock:
            return state()

    @app.post("/api/next")
    def next_level(body: TopicBody):
        with lock:
            game.next_level(body.topic)
            return state()

    @app.post("/api/submit")
    def submit(body: SQLBody):
        with lock:
            out = game.submit(body.sql)
            if out.get("broken"):
                return {"broken": True, "message": out["message"]}
            v = out["verdict"]
            return {
                "verdict": v.to_dict(),
                "outcome": out["outcome"].to_dict() if out["outcome"] else None,
                "first_pass": out["first_pass"],
                "status": game.status(),
            }

    @app.post("/api/tutor")
    def tutor(body: SQLBody):
        from sqlplay.engine import grader

        with lock:
            lv = game.current()
            v = grader.grade(game.db, lv, body.sql)
        return {"text": game.tutor(body.sql, v) if not v.passed else ""}

    @app.post("/api/pass_tip")
    def pass_tip(body: SQLBody):
        return {"text": game.pass_tip(body.sql)}

    @app.post("/api/hint")
    def hint():
        with lock:
            h = game.hint()
            return {"n": h[0], "text": h[1]} if h else {"n": None, "text": None}

    @app.post("/api/answer")
    def give_up():
        with lock:
            return {**game.give_up(), "status": game.status()}

    @app.post("/api/run")
    def run(body: SQLBody):
        with lock:
            return result_dict(game.run(body.sql))

    @app.post("/api/world")
    def set_world(body: WorldBody):
        with lock:
            try:
                game.set_world(body.slug)
            except ValueError as e:
                raise HTTPException(400, str(e))
            game.next_level()
            return state()

    @app.post("/api/topic")
    def set_topic(body: TopicBody):
        with lock:
            try:
                game.set_topic(body.topic)
            except ValueError as e:
                raise HTTPException(400, str(e))
            if body.topic:
                game.next_level(body.topic)
            return state()

    @app.post("/api/difficulty")
    def set_difficulty(body: DiffBody):
        with lock:
            game.set_difficulty(body.topic, body.difficulty)
            return state()

    @app.post("/api/expected")
    def set_expected(body: ToggleBody):
        with lock:
            game.set_show_expected(body.on)
            return state()

    @app.post("/api/setting")
    def set_setting(body: SettingBody):
        with lock:
            try:
                game.set_setting(body.key, body.on)
            except ValueError as e:
                raise HTTPException(400, str(e))
            return state()

    @app.post("/api/newworld")
    def new_world(body: ThemeBody):
        try:
            w = game.new_world(body.theme)
        except ai.AIError as e:
            raise HTTPException(400, str(e))
        with lock:
            return {"world": w, "state": state()}

    @app.post("/api/deleteworld")
    def delete_world(body: WorldBody):
        with lock:
            try:
                game.delete_world(body.slug)
            except ValueError as e:
                raise HTTPException(400, str(e))
            return state()

    @app.post("/api/exam/start")
    def exam_start(body: ExamStartBody):
        with lock:
            game.start_exam(body.minutes)
            return state()

    @app.post("/api/exam/answer")
    def exam_answer(body: ExamAnswerBody):
        with lock:
            if not game.exam:
                raise HTTPException(400, "No exam running")
            return result_dict(game.exam_answer(body.index, body.sql))

    @app.post("/api/exam/submit")
    def exam_submit():
        with lock:
            if not game.exam:
                raise HTTPException(400, "No exam running")
            summary = game.exam_submit(ai_comments=game.ai_available())
            return {"summary": summary, "state": state()}

    @app.post("/api/exam/quit")
    def exam_quit():
        with lock:
            game.exam = None
            return state()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def serve(game: Game, port: int = 8000, open_browser: bool = True) -> None:
    import uvicorn

    url = f"http://127.0.0.1:{port}/"
    print(f"psqlay web running at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(game, port), host="127.0.0.1", port=port, log_level="warning")
