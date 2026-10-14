"""psqlay: the terminal front end (psql-like REPL with a game on top)."""

from __future__ import annotations

import argparse
import sys
import textwrap
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers.sql import PostgresLexer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sqlplay.engine import ai
from sqlplay.engine.fmt import psql_table
from sqlplay.engine.levels import TOPICS
from sqlplay.engine.pg import PgError, default_cluster, home_dir

console = Console(highlight=False)

HELP = r"""
[bold]Playing[/]
  (type SQL, end with ;)   run it and grade it against the current question
  \hint                    next hint (3 per level, each costs 2 pts)
  \skip                    new question (counts as a skip)
  \answer                  give up: show the answer and why it works
  \level                   show the current question again

[bold]Exploring[/] (same as psql)
  \dt                      list tables
  \d <table>               show a table's columns
  \map                     show the join map

[bold]Choosing what to practise[/]
  \topic                   list topics and your level in each
  \topic <name>            lock to one topic, e.g. \topic joins
  \mix                     back to the mix (default)
  \level <topic> <1-5>     set your difficulty in a topic
  \world                   list worlds;  \world <name> to switch
  \newworld [theme]        AI: invent a new world (needs a key)

[bold]Exam[/]
  \exam [minutes]          10-question mock HOA, no hints (e.g. \exam 45)

[bold]Other[/]
  \score                   your stats
  \ai on|off               AI feedback on/off (needs a key)
  \help                    this help
  \q                       quit (progress is saved)
"""

EXAM_HELP = r"""
[bold]Exam mode[/]: type SQL to save it as your answer to the current question (you'll see
your rows, but not whether it's right). Revise as often as you like.
  \n  or \next             next question          \p or \prev   previous question
  \go <n>                  jump to question n     \list         all questions + status
  \dt  \d <table>  \map    explore as usual       \submit       finish and get graded
  \quit                    abandon the exam
"""


def wrap(s: str, indent: int = 2) -> str:
    return textwrap.fill(" ".join(s.split()), width=min(console.width, 100) - indent,
                         initial_indent=" " * indent, subsequent_indent=" " * indent)


class Shell:
    def __init__(self, game):
        self.g = game
        self.ai_on = game.ai_available()
        home_dir().mkdir(parents=True, exist_ok=True)
        self.session = PromptSession(
            history=FileHistory(str(home_dir() / "history")),
            lexer=PygmentsLexer(PostgresLexer),
        )
        self.exam_i = 0

    # ---------------------------------------------------------------- display
    def banner(self) -> None:
        st = self.g.status()
        w = st["world"]
        lv_bits = " · ".join(
            f"{t['topic'][:4].upper()} {t['difficulty']}" for t in st["topics"] if t["unlocked"]
        )
        mode = f"Topic: {TOPICS[st['locked']]}" if st["locked"] else "Mode: Mix"
        ai_txt = "[green]AI on[/]" if (st["ai"] and self.ai_on) else ("[dim]AI off[/]" if st["ai"] else "[dim]no AI key[/]")
        body = (
            f"World: {w['emoji']} [bold]{w['name']}[/]    {mode}    {ai_txt}\n"
            f"Score: [bold]{st['score']}[/]   Streak: 🔥 {st['streak']}   Levels: {lv_bits}"
        )
        console.print(Panel(body, title="[bold]psqlay[/]", title_align="left", border_style="cyan"))

    def show_level(self) -> None:
        lv = self.g.current()
        if self.g.needs_groupby_intro():
            console.print(Panel(self.g.groupby_intro(), title="🆕 New topic unlocked: GROUP BY / HAVING",
                                border_style="magenta"))
        src = {"builtin": "", "generated": " · generated", "ai": " · 🤖 AI"}.get(lv.source, "")
        console.print()
        console.print(
            f"[bold cyan]Level {lv.difficulty}[/] · {TOPICS.get(lv.topic, lv.topic)}{src}"
            f"[dim]{' ' * 4}{lv.points} pts[/]"
        )
        console.print()
        console.print(wrap(lv.question))
        if lv.columns:
            console.print()
            console.print("  [bold]Columns:[/] " + ", ".join(f'"{c}"' for c in lv.columns))
        if lv.ordered and lv.order_note:
            console.print(f"  [bold]Sort:[/]    {lv.order_note}")
        console.print()

    def print_result(self, res) -> None:
        if res is None:
            return
        if not res.ok:
            console.print(Text(res.error.psql_text(res.sql), style="red"))
            return
        console.print(psql_table(res.columns, res.rows, res.truncated))

    # ---------------------------------------------------------------- input
    def read_statement(self, prompt: str) -> str | None:
        """Read lines until ';' (SQL) or a single backslash command line."""
        lines: list[str] = []
        while True:
            p = prompt if not lines else " " * (len(prompt) - 5) + "...> "
            try:
                line = self.session.prompt(p)
            except KeyboardInterrupt:
                if lines:
                    lines = []
                    console.print("[dim](cleared)[/]")
                    continue
                return ""
            except EOFError:
                return None
            if not lines and line.strip().startswith("\\"):
                return line.strip()
            lines.append(line)
            text = "\n".join(lines).strip()
            if not text:
                lines = []
                continue
            if text.endswith(";") or text.endswith("\\g"):
                return text.removesuffix("\\g")

    # ---------------------------------------------------------------- loop
    def run(self) -> None:
        self.banner()
        console.print("[dim]Type \\help for commands. Write SQL and end it with ; to answer.[/]")
        self.show_level()
        while True:
            if self.g.exam:
                ex = self.g.exam
                rem = ex.remaining
                timer = f" [{rem // 60:02d}:{rem % 60:02d}]" if rem is not None else ""
                prompt = f"exam {self.exam_i + 1}/{len(ex.levels)}{timer}> "
                if rem == 0:
                    console.print("[bold yellow]⏰ Time's up! Submitting your exam...[/]")
                    self.exam_submit()
                    continue
            else:
                prompt = "psqlay> "
            stmt = self.read_statement(prompt)
            if stmt is None:
                break
            if not stmt:
                continue
            try:
                if stmt.startswith("\\"):
                    if self.command(stmt) == "quit":
                        break
                elif self.g.exam:
                    self.exam_sql(stmt)
                else:
                    self.answer(stmt)
            except (ai.AIError, ValueError, RuntimeError) as e:
                console.print(f"[red]{e}[/]")
        console.print("Bye! Progress saved. 👋")

    # ---------------------------------------------------------------- practice
    def answer(self, sql: str) -> None:
        out = self.g.submit(sql)
        if out.get("broken"):
            console.print(f"[yellow]{out['message']}[/]")
            return
        v = out["verdict"]
        self.print_result(v.result)
        console.print()
        if v.passed:
            if out["first_pass"]:
                o = out["outcome"]
                msg = f"[bold green]✓ PASS![/] +{o.points} pts   Score {o.score}   Streak 🔥 {o.streak}"
                if o.difficulty_after > o.difficulty_before:
                    msg += f"   [bold magenta]⬆ {TOPICS[self.g.current().topic]} → Level {o.difficulty_after}[/]"
                console.print(msg)
                if o.unlocked:
                    console.print(f"[bold magenta]🆕 Unlocked: {TOPICS[o.unlocked]}[/]")
            else:
                console.print("[bold green]✓ Still correct![/]")
            if self.ai_on:
                with console.status("[dim]🤖 tip...[/]", spinner="dots"):
                    tip = self.g.pass_tip(sql)
                if tip:
                    console.print(f"[cyan]🤖 {tip}[/]")
            console.print("[dim]Press Enter... (or keep exploring; \\skip for the next level)[/]")
            try:
                self.session.prompt("")
            except (KeyboardInterrupt, EOFError):
                pass
            self.next()
            return
        console.print(f"[bold red]✗ {v.message}[/]")
        if v.tip:
            console.print(wrap(v.tip))
        if self.ai_on:
            try:
                with console.status("[dim]🤖 thinking... (Ctrl-C to skip)[/]", spinner="dots"):
                    nudge = self.g.tutor(sql, v)
            except KeyboardInterrupt:
                nudge = ""
            if nudge:
                console.print(Text("🤖 ", style="cyan") + Text(nudge, style="cyan"))

    def next(self, topic: str | None = None) -> None:
        if self.g.ai_available() and self.ai_on:
            with console.status("[dim]Picking your next level...[/]", spinner="dots"):
                self.g.next_level(topic)
        else:
            self.g.next_level(topic)
        self.show_level()

    # ---------------------------------------------------------------- commands
    def command(self, line: str):
        parts = line.split()
        cmd, args = parts[0].lower(), parts[1:]
        if self.g.exam and cmd in ("\\n", "\\next", "\\p", "\\prev", "\\go", "\\list", "\\submit", "\\quit", "\\help", "\\h", "\\?"):
            return self.exam_command(cmd, args)
        if cmd in ("\\q", "\\quit", "\\exit"):
            return "quit"
        if cmd in ("\\h", "\\help", "\\?"):
            console.print(EXAM_HELP if self.g.exam else HELP)
        elif cmd == "\\hint":
            h = self.g.hint()
            if h is None:
                console.print("[yellow]No more hints. \\answer shows the solution.[/]")
            else:
                n, text = h
                console.print(f"[yellow]💡 Hint {n}/{len(self.g.current().hints)} (−2 pts):[/] {text}")
        elif cmd in ("\\skip", "\\next", "\\n"):
            self.next()
        elif cmd in ("\\answer", "\\giveup"):
            a = self.g.give_up()
            console.print(Panel(a["answer"], title="Answer", border_style="yellow"))
            console.print(wrap(a["explain"]))
            console.print()
            console.print(psql_table(a["columns"], a["rows"]))
            console.print("[dim]\\skip for the next level.[/]")
        elif cmd == "\\level":
            if len(args) == 2:
                self.g.set_difficulty(args[0], int(args[1]))
                console.print(f"{TOPICS[args[0]]} set to level {int(args[1])}.")
            else:
                self.show_level()
        elif cmd == "\\dt":
            t = Table(show_header=True, header_style="bold", box=None)
            t.add_column("Table"), t.add_column("Rows", justify="right"), t.add_column("Columns")
            for tb in self.g.schema():
                t.add_row(tb["table"], str(tb["rows"]), ", ".join(c["name"] for c in tb["columns"]))
            console.print(t)
        elif cmd == "\\d":
            self.describe(args[0] if args else None)
        elif cmd == "\\map":
            meta = self.g.world_meta()
            console.print(Panel((meta.get("join_map") or "").rstrip() + ("\n\n" + meta["notes"].rstrip() if meta.get("notes") else ""),
                                title="Join map", border_style="cyan"))
        elif cmd == "\\topic":
            if not args:
                self.topics()
            else:
                self.g.set_topic(args[0])
                console.print(f"Locked to [bold]{TOPICS[args[0]]}[/]. \\mix to go back.")
                self.next(args[0])
        elif cmd == "\\mix":
            self.g.set_topic(None)
            console.print("Back to the mix.")
        elif cmd == "\\world":
            if not args:
                for w in self.g.worlds():
                    mark = "→" if w["slug"] == self.g.world else " "
                    tag = " 🤖" if w["source"] == "ai" else ""
                    console.print(f" {mark} {w['emoji']} [bold]{w['slug']}[/] — {w['name']}{tag} ({w['levels']} levels)  [dim]{w['blurb']}[/]")
            else:
                self.g.set_world(args[0])
                self.banner()
                self.next()
        elif cmd == "\\newworld":
            if not self.g.ai_available():
                console.print("[yellow]Add OPENAI_API_KEY to .env to unlock AI worlds.[/]")
                return
            theme = " ".join(args) or None
            with console.status("[dim]🤖 Designing a new world (can take a minute)...[/]", spinner="dots"):
                w = self.g.new_world(theme)
            console.print(f"[green]New world:[/] {w['emoji']} [bold]{w['name']}[/] ({w['slug']}). "
                          f"Switch with \\world {w['slug']}")
        elif cmd == "\\exam":
            minutes = int(args[0]) if args else None
            with console.status("[dim]Building your exam...[/]", spinner="dots"):
                ex = self.g.start_exam(minutes)
            self.exam_i = 0
            console.print(Panel(
                f"{len(ex.levels)} questions in {self.g.status()['world']['name']}. No hints. "
                + (f"Time limit: {minutes} min. " if minutes else "No time limit. ")
                + "Type SQL to save an answer; \\next/\\prev to move; \\submit when done. \\help for more.",
                title="📝 Exam", border_style="magenta"))
            self.exam_show()
        elif cmd == "\\score":
            self.score()
        elif cmd == "\\ai":
            if not self.g.ai_available():
                console.print("[yellow]No OPENAI_API_KEY in .env.[/]")
            else:
                self.ai_on = (args[0].lower() != "off") if args else not self.ai_on
                console.print(f"AI feedback {'on' if self.ai_on else 'off'}.")
        else:
            console.print(f"[red]Unknown command {cmd}.[/] \\help lists commands.")

    def describe(self, table: str | None) -> None:
        tables = self.g.schema()
        if not table:
            for tb in tables:
                self.describe(tb["table"])
            return
        tb = next((t for t in tables if t["table"] == table.lower()), None)
        if not tb:
            console.print(f'[red]Did not find any relation named "{table}".[/]')
            return
        rows = []
        for c in tb["columns"]:
            extra = "PK" if c["pk"] else (f"→ {c['fk']}" if c["fk"] else "")
            rows.append((c["name"], c["type"], extra))
        console.print(f'               Table "{tb["table"]}"  ({tb["rows"]} rows)')
        console.print(psql_table(["Column", "Type", "Key"], rows).rsplit("\n", 1)[0])
        console.print()

    def topics(self) -> None:
        st = self.g.status()
        for t in st["topics"]:
            lock = "" if t["unlocked"] else "  [dim](locked: pass 3 aggregate levels)[/]"
            mark = "→" if st["locked"] == t["topic"] else " "
            console.print(f" {mark} [bold]{t['topic']:11}[/] {t['name']:32} level {t['difficulty']}   "
                          f"passed {t['passed']}/{t['attempted']}{lock}")

    def score(self) -> None:
        st = self.g.status()
        console.print(f"Score [bold]{st['score']}[/]   Streak 🔥 {st['streak']}   Best streak {st['best_streak']}")
        self.topics()

    # ---------------------------------------------------------------- exam
    def exam_show(self) -> None:
        ex = self.g.exam
        lv = ex.levels[self.exam_i]
        saved = "  [green](answer saved)[/]" if ex.answers.get(self.exam_i) else ""
        console.print()
        console.print(f"[bold magenta]Question {self.exam_i + 1}/{len(ex.levels)}[/] · {lv.points} pts{saved}")
        console.print(wrap(lv.question))
        if lv.columns:
            console.print("  [bold]Columns:[/] " + ", ".join(f'"{c}"' for c in lv.columns))
        if lv.ordered and lv.order_note:
            console.print(f"  [bold]Sort:[/]    {lv.order_note}")
        console.print()

    def exam_sql(self, sql: str) -> None:
        res = self.g.exam_answer(self.exam_i, sql)
        self.print_result(res)
        console.print("[green]Answer saved.[/] [dim]\\next for the next question, \\submit when done.[/]")

    def exam_command(self, cmd: str, args: list[str]):
        ex = self.g.exam
        n = len(ex.levels)
        if cmd in ("\\n", "\\next"):
            self.exam_i = min(n - 1, self.exam_i + 1)
            self.exam_show()
        elif cmd in ("\\p", "\\prev"):
            self.exam_i = max(0, self.exam_i - 1)
            self.exam_show()
        elif cmd == "\\go" and args:
            self.exam_i = max(0, min(n - 1, int(args[0]) - 1))
            self.exam_show()
        elif cmd == "\\list":
            for i, lv in enumerate(ex.levels):
                done = "✓" if ex.answers.get(i) else "·"
                console.print(f" {done} {i + 1:2}. [dim]L{lv.difficulty}[/] {lv.question[:80]}")
        elif cmd == "\\submit":
            blank = n - len([a for a in ex.answers.values() if a.strip()])
            if blank:
                console.print(f"[yellow]{blank} question(s) still blank.[/] Submit anyway? (y/n)")
                if self.session.prompt("> ").strip().lower() != "y":
                    return
            self.exam_submit()
        elif cmd == "\\quit":
            self.g.exam = None
            console.print("Exam abandoned.")
            self.show_level()
        elif cmd in ("\\help", "\\h", "\\?"):
            console.print(EXAM_HELP)

    def exam_submit(self) -> None:
        with console.status("[dim]Grading" + (" and writing comments" if self.ai_on else "") + "...[/]", spinner="dots"):
            s = self.g.exam_submit(ai_comments=self.ai_on)
        mins, secs = divmod(s["seconds"], 60)
        pct = round(100 * s["score"] / s["total"]) if s["total"] else 0
        console.print(Panel(
            f"[bold]{s['correct']}/{s['count']} correct[/]   {s['score']}/{s['total']} pts ({pct}%)   time {mins}m {secs}s",
            title="📝 Exam results", border_style="magenta"))
        for r in s["results"]:
            mark = "[green]✓[/]" if r["passed"] else "[red]✗[/]"
            console.print(f"{mark} [bold]Q{r['index'] + 1}[/] (L{r['difficulty']}, {r['points']} pts) {r['question'][:90]}")
            if not r["passed"]:
                console.print(f"   [red]{r['message']}[/]")
                if r["ai_comment"]:
                    console.print(f"   [cyan]🤖 {r['ai_comment']}[/]")
                elif r["tip"]:
                    console.print(f"   {r['tip']}")
                console.print(textwrap.indent(r["answer"], "     [dim]") .replace("\n", "[/]\n") + "[/]")
        console.print()
        self.show_level()


# -------------------------------------------------------------------- entry
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="psqlay", description="SQL practice playground")
    ap.add_argument("command", nargs="?", default="play",
                    choices=["play", "web", "stop", "reset", "doctor"],
                    help="play (default), web, stop the private Postgres, reset progress, doctor")
    ap.add_argument("--port", type=int, default=8000, help="web port (default 8000)")
    ap.add_argument("--no-browser", action="store_true", help="web: don't open a browser")
    args = ap.parse_args(argv)

    if args.command == "stop":
        default_cluster().stop()
        print("Stopped psqlay's private Postgres.")
        return 0
    if args.command == "doctor":
        return doctor()

    from sqlplay.engine.game import Game

    try:
        with console.status("[dim]Starting psqlay's private Postgres...[/]", spinner="dots"):
            game = Game()
    except PgError as e:
        console.print(f"[red]{e}[/]")
        return 1

    if args.command == "reset":
        from sqlplay.engine import progress

        if input("Reset all progress (score, levels, history)? (y/n) ").strip().lower() == "y":
            progress.reset(game.db)
            print("Progress reset.")
        return 0
    if args.command == "web":
        from sqlplay.web.app import serve

        serve(game, port=args.port, open_browser=not args.no_browser)
        return 0
    Shell(game).run()
    return 0


def doctor() -> int:
    from sqlplay.engine.pg import find_bin_dir

    ok = True
    try:
        print("Postgres binaries:", find_bin_dir())
    except PgError as e:
        print(e)
        ok = False
    c = default_cluster()
    print("Data folder:", c.base, "(initialised)" if c.initialized() else "(not yet created)")
    print("Server running:", c.running())
    print("OpenAI key:", "found" if ai.available() else "not set (AI features off)")
    if ai.available():
        print("Models: generate =", ai.gen_model(), "| feedback =", ai.feedback_model())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
