# DevDrop

**Simple local file and text sharing between your devices.**

DevDrop lets you quickly send files, photos, and text from another device on your local network directly to your computer.

No accounts. No cloud. Just your devices.

## Features

- Local network file sharing
- Text sharing
- 9-digit pairing code
- Mobile-friendly web interface
- Upload files from any device with a browser
- Take and send photos directly from a phone
- Drag & drop support on desktop
- Image previews before sending
- Automatic duplicate filename handling
- Separate session folder for every launch
- Optional session cleanup on exit
- Minimal dark UI

## How it works

Start DevDrop on your computer:

```bash
python devdrop.py
```

DevDrop will display something like:

```text
╭────────────────────────────────────────────────────────╮
│                                                        │
│                        DevDrop                         │
│                                                        │
│              Local sharing made simple.                │
│                                                        │
╰────────────────────────────────────────────────────────╯

Pairing code   223 975 676
Open           http://192.168.0.107:8765
Session        C:\Users\user\DevDrop\session-2026-08-18_15-06-38

Waiting for devices...
```

On another device:

1. Connect to the same local network.
2. Open the displayed address in a browser.
3. Enter the pairing code.
4. Send text, files, or photos.

Received data is stored inside the current DevDrop session directory.

## Installation

### Requirements

- Python 3.10+
- Devices connected to the same local network

Clone the repository:

```bash
git clone https://github.com/devid-wp/Dev-drop.git
cd devdrop
```

Create a virtual environment:Ы

### Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run DevDrop:

```powershell
python devdrop.py
```

### Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python devdrop.py
```

## Session folders

Every launch creates a new session directory:

```text
~/DevDrop/session-YYYY-MM-DD_HH-MM-SS/
```

For example:

```text
session-2026-08-18_15-06-38/
├── text-001.txt
├── photo.jpg
├── photo (1).jpg
└── archive.zip
```

When DevDrop exits, it asks whether the current session should be deleted:

```text
Delete this session folder? [y/N]:
```

The folder is only deleted when explicitly confirmed with `y` or `yes`.

## Project structure

```text
devdrop/
├── app/
│   └── main.py
├── web/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── devdrop.py
├── requirements.txt
└── README.md
```

## Tech stack

- FastAPI
- Uvicorn
- Vanilla JavaScript
- HTML
- CSS

## Security

DevDrop is currently designed as a lightweight local-network utility.

The pairing system provides basic protection against accidental access, but **DevDrop v0.1 should not be treated as a secure or encrypted file-transfer protocol**.

Do not expose the DevDrop server directly to the public internet.

## Roadmap

Possible future improvements:

- Transfer progress
- Live device status
- Improved authentication
- HTTPS / encrypted transfers
- Better Linux integration
- Packaged Windows and Linux releases
- QR-code pairing

## License

MIT
## Transfer history storage

History uses the standard-library SQLite driver. The database is
`transfer_history.sqlite3` beside the legacy `transfer_history.json`: the GUI
uses the configured session root; callers without `HISTORY_PATH` use the current
session directory. It is created lazily on the first history read or write.
The existing API returns the most recent 20 records in insertion order, and the
GUI continues to show newest first. SQLite retains older metadata until an
explicit history clear. File contents are never stored in the database.

The first database operation validates and imports the legacy JSON in one
transaction, together with a completion marker. All objects and extra metadata
fields are preserved, and the source file is never changed or removed. Reopening
or clearing the database does not repeat the import. An absent JSON is recorded
as a completed empty import; a JSON added later is not imported automatically.
Invalid JSON, invalid known field types, unsupported schema versions and storage
errors raise a history error (HTTP 503), rather than silently clearing data.
After correcting a failed import's source, retry the operation. Do not delete a
working database to retry migration: that also deletes its completion marker.

Connections are opened and closed per operation. `BEGIN IMMEDIATE`, parameterized
inserts and a 10-second lock timeout protect concurrent writers. Schema version
1 is recorded with `PRAGMA user_version`. Metadata objects are encoded as JSON
text inside rows to preserve legacy fields without introducing a device model.

History deletion clears SQLite records, but deliberately leaves the original
JSON backup intact. Filesystem file saves and SQLite commits are separate:
a history failure after a successful file save can return 503 even though the
file exists. There is no automatic reconciliation at this stage. Back up both
the SQLite database and the legacy JSON while the application is stopped.
