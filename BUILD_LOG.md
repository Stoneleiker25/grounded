# Build Log

Track every **restore** and **live start** for Grounded, plus the lessons worth keeping.

* `.\start.ps1` — legacy Flask app at the repo root (port 5000)
* `.\v2\run.ps1` — FastAPI + frontend rewrite (ports 8000 / 5173)

Both append their run results here, so this file is one continuous history across both stacks.
The **Lessons learned** table below is maintained by hand — that is the part you mine when writing the README.

---

## Quick status legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Step succeeded |
| ❌ | Step failed — stop and fix before continuing |
| ⚠️ | Warning — may work, but investigate |
| 🚩 | Red flag — likely wrong API, bad config, or broken route |

---

## Red flags to watch for

Use this checklist when reading a log entry. If you see any of these, something is probably wrong.

### Restore (`pip install`)

| Red flag | What it usually means |
|----------|----------------------|
| `ERROR: Could not find a version` | Wrong package name or Python version mismatch |
| `ModuleNotFoundError` after restore | `requirements.txt` missing a dependency |
| `Permission denied` | Run terminal as user, not admin-only path issues |
| `pip` not found | Python not on PATH |

### Start / live server

| Red flag | What it usually means |
|----------|----------------------|
| `Address already in use` / port `5000` in use | Old Flask process still running — kill it first |
| `ERR_CONNECTION_REFUSED` in browser | Server never started or crashed immediately |
| `TemplateNotFound` | `index.html` not in `templates/` |
| `ImportError` / `ModuleNotFoundError: flask` | Restore failed or wrong virtualenv active |
| `Running on http://127.0.0.1:5000` missing | Flask did not bind — check traceback above |

### Wrong API / route issues

| Red flag | What it usually means |
|----------|----------------------|
| Health check **404** | Route `/` missing or renamed in `app.py` |
| Health check **500** | Server error in view — check Flask traceback |
| Health check **connection error** | Server not listening yet or wrong host/port |
| Browser shows blank page but **200** | Template or static asset problem |

### General errors

| Red flag | What it usually means |
|----------|----------------------|
| `Traceback (most recent call last)` | Python crash — read the last line of the traceback |
| `WARNING: This is a development server` | Normal for local dev (not a failure) |
| `Failed to authenticate` / git errors | Unrelated to app run — check GitHub auth separately |

---

## How to run and log

```powershell
.\start.ps1
```

This will:

1. **Restore** — `pip install -r requirements.txt`
2. **Health check** — request `http://127.0.0.1:5000/` (after server starts)
3. **Start live** — run `python app.py` (keeps running until you press `Ctrl+C`)
4. **Append** — write results to this file

---

## Lessons learned

Durable notes, kept by hand. The auto-appended entries below say *what* failed on a
given run; this table says *why it happened and what I now know*. Add a row whenever
you burn more than ten minutes on something. This is the raw material for the
"what I learned" section of the README.

| Date | Symptom | Root cause | Fix | Lesson |
|------|---------|-----------|-----|--------|
| 2026-08-31 | `SAVE BRIEFING` hung 5s then HTTP 500, `database is locked` | `save_briefing()` held a write transaction, then called `log_history()`, which opened a **second connection** to the same SQLite file and blocked on the lock its own caller held | Inline the history INSERT onto the connection already open | SQLite locks are per-connection. A helper that opens its own connection cannot be called from inside an open write transaction. |
| 2026-08-31 | Orphan rows accepted; `FOREIGN KEY` declarations did nothing | SQLite parses FK constraints but **ignores them unless enabled per connection** | `PRAGMA foreign_keys = ON` on every new connection | A constraint you never switched on is a comment. Verify enforcement, don't assume it. |
| 2026-08-31 | `git status` showed `db.py` as **U** (untracked) | Never `git add`ed — two commits existed but neither included it | `git add db.py` | The file with all the logic had zero version history. Check `git status` before trusting that work is safe. |
| 2026-08-31 | Layout unusable below ~700px, content 472px wide in a 390px viewport | `grid-cols-2` with no responsive prefix anywhere in the file | `grid-cols-1 lg:grid-cols-2` | Test at mobile width *while* building, not after. |
| 2026-08-31 | `min-h-[calc(100vh-53px)]` misaligned | 53px was a hand-measured header height; real value was 55px, and 67px at mobile width | Flex column with `flex-1` and let the browser compute it | Hardcoded measurements are wrong the moment anything changes. Let layout derive itself. |
| 2026-08-31 | Screen reader announced "button, button, button" 15 times | Icon-only buttons with no accessible name | `aria-label` on each; `aria-hidden="true"` on decorative SVGs | An icon is not a name. |
| 2026-08-31 | Tests passed locally, failed on a clean checkout (8 failures) | Test env vars were set at the top of `test_api.py`, but `settings` is built at first import — and `test_analysis.py` sorts earlier alphabetically, so config was frozen first. A local `.env` masked it | Move env setup to `app/tests/conftest.py`, which pytest loads before any test module | **Passing tests on your own machine proves nothing.** Always run from a clean copy with no local config. |
| 2026-08-31 | Frontend blocked by CORS on a non-default port | `allow_origins` pinned to `:5173`, but the README told users to switch ports when 5173 was taken | `allow_origin_regex` accepting any loopback origin | Config that contradicts your own setup instructions will break exactly the person following them. |
| 2026-08-31 | Same event written to both `history` and `bullet_status_history` | Two audit tables, no constraint keeping them in sync | One append-only table | Two sources of truth for one fact will drift. Pick one. |
| 2026-08-31 | Tailwind styling would have broken in production | `cdn.tailwindcss.com` compiles CSS in the browser — explicitly not for production | Proper install, or hand-written CSS | Play-CDN builds are for prototypes only. |

---

## Log entries

<!-- Entries below are auto-appended by start.ps1 -->
---

### 2026-08-31 01:58:34 | Session 20260831-015834

| Step | Status |
|------|--------|
| **Overall** | ❌ FAILED |
| Restore (pip install) | ✅ OK |
| Start live (python app.py) | ⚠️ PORT IN USE |
| Health check (GET /) | ⚠️ SKIPPED |

**URL:** `http://127.0.0.1:5000/`  
**Health detail:** Not run  
**Logged:** 2026-08-31 01:58:36  

🚩 **Red flags:** port in use

<details>
<summary>Restore output</summary>

```
Requirement already satisfied: flask>=3.0.0 in C:\Users\stone\AppData\Local\Programs\Python\Python312\Lib\site-packages (from -r requirements.txt (line 1)) (3.1.3)
Requirement already satisfied: blinker>=1.9.0 in C:\Users\stone\AppData\Local\Programs\Python\Python312\Lib\site-packages (from flask>=3.0.0->-r requirements.txt (line 1)) (1.9.0)
Requirement already satisfied: click>=8.1.3 in C:\Users\stone\AppData\Local\Programs\Python\Python312\Lib\site-packages (from flask>=3.0.0->-r requirements.txt (line 1)) (8.4.2)
Requirement already satisfied: itsdangerous>=2.2.0 in C:\Users\stone\AppData\Local\Programs\Python\Python312\Lib\site-packages (from flask>=3.0.0->-r requirements.txt (line 1)) (2.2.0)
Requirement already satisfied: jinja2>=3.1.2 in C:\Users\stone\AppData\Local\Programs\Python\Python312\Lib\site-packages (from flask>=3.0.0->-r requirements.txt (line 1)) (3.1.6)
Requirement already satisfied: markupsafe>=2.1.1 in C:\Users\stone\AppData\Local\Programs\Python\Python312\Lib\site-packages (from flask>=3.0.0->-r requirements.txt (line 1)) (3.0.3)
Requirement already satisfied: werkzeug>=3.1.0 in C:\Users\stone\AppData\Local\Programs\Python\Python312\Lib\site-packages (from flask>=3.0.0->-r requirements.txt (line 1)) (3.1.8)
Requirement already satisfied: colorama in C:\Users\stone\AppData\Local\Programs\Python\Python312\Lib\site-packages (from click>=8.1.3->flask>=3.0.0->-r requirements.txt (line 1)) (0.4.6)
System.Management.Automation.RemoteException
[notice] A new release of pip is available: 26.1.2 -> 26.2.1
[notice] To update, run: python.exe -m pip install --upgrade pip
```

</details>

<details>
<summary>Server output</summary>

```
Port 5000 is already in use. Stop the other process or change the port.
```

</details>

---

### 2026-08-31 03:09:32 | Session 20260831-030932

| Step | Status |
|------|--------|
| **Overall** | OK |
| Restore (`pip install`) | OK |
| Start live (`uvicorn`) | OK |
| Health check (`GET /api/health`) | OK |

**Stack:** FastAPI + vanilla JS  
**URL:** `http://127.0.0.1:5173`  
**API:** `http://127.0.0.1:8000`  
**Health detail:** HTTP 200 from /api/health  
**Logged:** 2026-08-31 03:10:50  

No red flags detected.

<details>
<summary>Restore output</summary>

```
Downloading pydantic_settings-2.14.0-py3-none-any.whl (60 kB)
Using cached anthropic-1.2.0-py3-none-any.whl (1.3 MB)
Downloading rapidfuzz-3.14.6-cp312-cp312-win_amd64.whl (1.7 MB)
   ---------------------------------------- 1.7/1.7 MB 47.4 MB/s  0:00:00
Using cached python_dotenv-1.2.2-py3-none-any.whl (22 kB)
Using cached httpx-0.28.1-py3-none-any.whl (73 kB)
Downloading pytest-9.1.1-py3-none-any.whl (386 kB)
Downloading pydantic_core-2.46.3-cp312-cp312-win_amd64.whl (2.1 MB)
   ---------------------------------------- 2.1/2.1 MB 113.2 MB/s  0:00:00
Using cached anyio-4.14.2-py3-none-any.whl (125 kB)
Using cached docstring_parser-0.18.0-py3-none-any.whl (22 kB)
Using cached httpcore-1.0.9-py3-none-any.whl (78 kB)
Using cached httpx2-2.12.0-py3-none-any.whl (95 kB)
Using cached httpcore2-2.12.0-py3-none-any.whl (83 kB)
Using cached jiter-0.16.0-cp312-cp312-win_amd64.whl (196 kB)
Downloading pluggy-1.6.0-py3-none-any.whl (20 kB)
Using cached sniffio-1.3.1-py3-none-any.whl (10 kB)
Using cached typing_extensions-4.16.0-py3-none-any.whl (45 kB)
Downloading annotated_doc-0.0.5-py3-none-any.whl (5.3 kB)
Using cached annotated_types-0.8.0-py3-none-any.whl (13 kB)
Downloading click-8.5.0-py3-none-any.whl (125 kB)
Using cached colorama-0.4.6-py2.py3-none-any.whl (25 kB)
Downloading greenlet-3.5.5-cp312-cp312-win_amd64.whl (324 kB)
Using cached h11-0.16.0-py3-none-any.whl (37 kB)
Downloading httptools-0.8.0-cp312-cp312-win_amd64.whl (90 kB)
Downloading idna-3.19-py3-none-any.whl (68 kB)
Downloading iniconfig-2.3.0-py3-none-any.whl (7.5 kB)
Downloading packaging-26.3-py3-none-any.whl (129 kB)
Downloading pygments-2.21.0-py3-none-any.whl (1.3 MB)
   ---------------------------------------- 1.3/1.3 MB 61.8 MB/s  0:00:00
Using cached pyyaml-6.0.3-cp312-cp312-win_amd64.whl (154 kB)
Downloading starlette-1.6.0-py3-none-any.whl (75 kB)
Using cached truststore-0.10.4-py3-none-any.whl (18 kB)
Using cached typing_inspection-0.4.4-py3-none-any.whl (14 kB)
Downloading watchfiles-1.2.0-cp312-cp312-win_amd64.whl (288 kB)
Downloading websockets-17.1-cp312-cp312-win_amd64.whl (217 kB)
Using cached certifi-2026.7.22-py3-none-any.whl (136 kB)
Installing collected packages: websockets, typing-extensions, truststore, sniffio, rapidfuzz, pyyaml, python-dotenv, pygments, pluggy, packaging, jiter, iniconfig, idna, httptools, h11, greenlet, docstring-parser, colorama, click, certifi, annotated-types, annotated-doc, uvicorn, typing-inspection, SQLAlchemy, pytest, pydantic-core, httpcore2, httpcore, anyio, watchfiles, starlette, pydantic, httpx2, httpx, pydantic-settings, fastapi, anthropic

Successfully installed SQLAlchemy-2.0.52 annotated-doc-0.0.5 annotated-types-0.8.0 anthropic-1.2.0 anyio-4.14.2 certifi-2026.7.22 click-8.5.0 colorama-0.4.6 docstring-parser-0.18.0 fastapi-0.141.1 greenlet-3.5.5 h11-0.16.0 httpcore-1.0.9 httpcore2-2.12.0 httptools-0.8.0 httpx-0.28.1 httpx2-2.12.0 idna-3.19 iniconfig-2.3.0 jiter-0.16.0 packaging-26.3 pluggy-1.6.0 pydantic-2.13.3 pydantic-core-2.46.3 pydantic-settings-2.14.0 pygments-2.21.0 pytest-9.1.1 python-dotenv-1.2.2 pyyaml-6.0.3 rapidfuzz-3.14.6 sniffio-1.3.1 starlette-1.6.0 truststore-0.10.4 typing-extensions-4.16.0 typing-inspection-0.4.4 uvicorn-0.46.0 watchfiles-1.2.0 websockets-17.1
```

</details>

<details>
<summary>Server output</summary>

```
INFO:     127.0.0.1:49700 - "GET /api/health HTTP/1.1" 200 OK
INFO:     Started server process [6444]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

</details>

