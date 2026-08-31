# Build Log

Track every **restore** and **live start** for Grounded. New entries are appended automatically when you run `start.ps1`.

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

