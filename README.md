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