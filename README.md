# Grounded

A notes management and briefing dashboard built with Flask and Tailwind CSS.

## Features

- **Notes Management** — paste or upload notes, view saved notes, select items for briefing
- **Briefing Area** — review, edit, approve, and save briefing drafts
- **Wireframe UI** — grayscale dashboard layout matching the project wireframe

## Requirements

- Python 3.10+
- pip

## Setup

```bash
pip install -r requirements.txt
```

## Run

```powershell
.\start.ps1
```

This restores dependencies, starts the server, health-checks `http://127.0.0.1:5000/`, and appends results to [BUILD_LOG.md](BUILD_LOG.md).

Or manually:

```bash
python app.py
```

Open http://127.0.0.1:5000 in your browser.

## Build log

See [BUILD_LOG.md](BUILD_LOG.md) for restore/start history, red flags, and error patterns to watch for.

## Project Structure

```
grounded/
├── app.py              # Flask application
├── start.ps1           # Restore, start live, append BUILD_LOG.md
├── BUILD_LOG.md        # Restore/start history and red-flag guide
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Dashboard UI
└── Wireframe.jpg       # Design reference
```

## License

MIT
