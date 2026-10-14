# Set up psqlay with an AI coding agent

Copy everything in the box below and paste it into your AI coding agent (Claude Code, Codex, Cursor,
Windsurf, Gemini CLI, and so on), opened in any folder. The agent installs psqlay once and then tells
you how to play. It takes about 5 minutes, and most of that is downloading PostgreSQL if you don't
have it yet.

````text
Set up psqlay for me: a local SQL practice game (https://github.com/itsalexi/sqlplay).
Do it once, step by step, and briefly tell me what you're doing at each step.

RULES
- Ask me before installing anything system-wide (PostgreSQL, uv, Homebrew, apt packages).
- Never ask me to paste an API key into this chat. If I want the optional AI features, I will put
  the key into the .env file myself.
- Don't touch my existing PostgreSQL server or databases. psqlay creates and runs its own private
  Postgres in ~/.sqlplay, which listens on a local socket only and needs no password.
- Supported: macOS and Linux. On Windows, do everything inside WSL (Ubuntu). If WSL isn't installed,
  stop and tell me to run `wsl --install` in an admin PowerShell, then restart.

1. CHECK TOOLS
   - git: `git --version`
   - uv: `uv --version`. If it's missing, install it with
     `curl -LsSf https://astral.sh/uv/install.sh | sh`, then make sure `uv` is on PATH.
   - PostgreSQL SERVER programs (initdb, pg_ctl, postgres), version 14 or newer. Look in:
     `pg_config --bindir`, `/Library/PostgreSQL/*/bin`, `/Applications/Postgres.app/Contents/Versions/*/bin`,
     `/opt/homebrew/opt/postgresql@*/bin`, `/usr/local/opt/postgresql@*/bin`, `/usr/lib/postgresql/*/bin`.
     If they're missing, install PostgreSQL (ask me first):
       macOS (Homebrew):  brew install postgresql@17
       Debian/Ubuntu/WSL: sudo apt update && sudo apt install -y postgresql
       Fedora:            sudo dnf install -y postgresql-server
     The system Postgres service does NOT need to be running or configured.

2. GET THE CODE
   Clone it into ~/psqlay unless I say otherwise:
     git clone https://github.com/itsalexi/sqlplay ~/psqlay

3. INSTALL THE COMMAND
     cd ~/psqlay && uv tool install -e . --with openai
     uv tool update-shell        # puts ~/.local/bin on PATH if needed
   Then check that `psqlay --help` works (open a new shell if PATH changed).

4. POINT IT AT POSTGRES (only if needed)
   Run `psqlay doctor`. If it says it can't find the PostgreSQL server binaries, create ~/psqlay/.env
   containing one line, using the folder that has initdb in it:
     SQLPLAY_PG_BIN=/path/to/postgres/bin
   Then run `psqlay doctor` again until it finds them.

5. ONE-TIME INIT
     psqlay setup
   It should print "psqlay is set up." and list 3 worlds (pizza, movies, school).
   If it fails:
   - "initdb: cannot be run as root": run as a normal user, not root.
   - Port 54329 already in use: add SQLPLAY_PORT=54331 (or another free port) to ~/psqlay/.env.
   - Anything else: show me the error and the last lines of ~/.sqlplay/postgres.log.

6. OPTIONAL: AI FEATURES (tutor feedback, AI-written levels, new AI worlds)
   Don't ask for my key. Instead, tell me:
     "To turn on AI, run: cp ~/psqlay/.env.example ~/psqlay/.env, open ~/psqlay/.env, and paste your
      OpenAI key after OPENAI_API_KEY=. It costs roughly $0.10-0.30 per hour of practice, and you
      can switch it off any time with \ai off."
   After I've done it, `psqlay doctor` should show "OpenAI key: found".

7. OPTIONAL: VERIFY
     cd ~/psqlay && uv run pytest -q
   All tests should pass. They use their own throwaway database.

8. FINISH
   Tell me:
   - `psqlay` starts it in the terminal, and `psqlay web` opens it in the browser (http://127.0.0.1:8000).
   - Type SQL ending in ; to answer, or end it with \g to just run it without grading. \help lists all
     commands.
   - `psqlay stop` stops its private database, and `psqlay doctor` checks the setup.
````

## What the agent will do

| Step | What happens | Changes your system? |
|---|---|---|
| Check tools | Looks for git, uv and the PostgreSQL server programs | No |
| Install PostgreSQL / uv | Only if they're missing, and only after you say yes | Yes (with permission) |
| Clone and install | Copies the repo to `~/psqlay` and adds a `psqlay` command in `~/.local/bin` | Your home folder only |
| `psqlay setup` | Creates a private database in `~/.sqlplay` and loads the worlds | Your home folder only |

To uninstall later:

```bash
psqlay stop && uv tool uninstall sqlplay && rm -rf ~/.sqlplay ~/psqlay
```
