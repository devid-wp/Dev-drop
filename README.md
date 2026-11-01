# DevDrop

**Simple local file and text sharing between your devices.**

DevDrop lets you quickly send files, photos, and text from another device on your local network directly to your computer.

No accounts. No cloud. Just your devices.

## Features

- Local network file sharing
- Text sharing
- One-use QR pairing with explicit owner approval
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

Install the command entry point, then start the server:

```bash
pip install -e .
devdrop serve
```

On first launch, `devdrop serve` offers to create a local HTTPS identity. It
reuses existing local CA/certificate files, protects keys with owner-only OS
permissions, and never enables HTTP. Optional Advanced Security Mode encrypts
keys with a password. Existing encrypted local keys can be migrated to OS-only
storage after consent; the encrypted originals are retained. The generated
identity includes current LAN addresses. Android obtains the CA identity from
the QR scanned directly from the PC; browser certificate trust remains a
separate OS/browser setup. See
[HTTPS and certificate trust](docs/TRANSPORT.md).

DevDrop displays the HTTPS address, QR pairing state, and save location:

```text
╭────────────────────────────────────────────────────────╮
│                                                        │
│                        DevDrop                         │
│                                                        │
│              Local sharing made simple.                │
│                                                        │
╰────────────────────────────────────────────────────────╯

Open           https://192.168.0.107:8765
Session        C:\Users\user\DevDrop\session-2026-08-18_15-06-38

Waiting for devices...
```

On Android:

1. Connect to the same local network.
2. Open Dev-Drop and tap **Scan QR**.
3. Compare the short code shown on the phone with the request on the PC, enter
   that code in the local Web Panel, TUI, or desktop GUI, and approve explicitly.
4. Choose files to send. Each transfer still requires its own owner approval.

From a terminal, `devdrop pair` prints the same time-limited QR. The pairing
token is one use and expires after two minutes. See
[the QR protocol](docs/QR_PAIRING.md) for trust and compatibility details.

Received data is stored inside the current DevDrop session directory.

### Local Web Panel

While the server is running, open its HTTPS loopback address on the same
computer. The browser must trust the provisioned Dev-Drop CA; never bypass a
certificate warning:

```text
https://127.0.0.1:8765/panel
```

Start the HTTPS server and panel with `./run-panel.sh`; it uses the same
first-run TLS flow as `devdrop serve`.

### Terminal CLI

Run `./start-devdrop.sh` to open the interactive TUI. To run a CLI command
without activating `.venv` or typing the Python module path, pass it to the
same script:

```bash
./start-devdrop.sh serve
./start-devdrop.sh pair
./start-devdrop.sh doctor
```

The script creates `.venv` and installs the project dependencies on first run.

The panel is served by the existing FastAPI process and is restricted to direct
loopback requests with a loopback Host. It shows paired sessions, discovered
servers, incoming approvals, outgoing offer states, history, pairing details
and the exposed server configuration. Each incoming request requires an
explicit review and decision. Certificate fingerprints and expiry are not
available from the existing browser API, and settings are changed with
`devdrop config` rather than from the panel. The existing `/` page remains the
browser client used by phones.

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
pip install -e .
```

Run DevDrop:

```powershell
devdrop serve
```

### Linux

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
devdrop serve
```

The previous `python devdrop.py` server launcher remains available.

## CLI

The CLI is the primary control surface for the local server. It uses the
existing pinned loopback HTTPS management API for status, pairing-code display,
pending approvals and history. It never prints session tokens. The owner must
explicitly approve or reject every pending transfer.

```bash
devdrop --help
devdrop tui
devdrop status
devdrop pair
devdrop transfers
devdrop transfers --approve REQUEST_ID
devdrop transfers --reject REQUEST_ID
devdrop history --json
devdrop devices
devdrop config
devdrop doctor
```

Set the server port and session root with `devdrop config --port 8765
--session-root ~/DevDrop`. `devdrop serve` uses that configuration and retains
session files on shutdown. `devdrop doctor --json` reports TLS, storage, port,
and local-server checks. Commands that expose data support `--json` where it is
useful for scripts. `python devdrop.py` remains as a backward-compatible
server launcher. Desktop GUI startup remains available through `devdrop.bat`
on Windows or `python devdrop_gui.py`.

The CLI does not yet provide remote `send` or remote-client `pair`: the project
has no CLI credential store for independently trusted remote CA certificates
and Bearer sessions. Use the existing GUI, browser or Android client for sends;
these interfaces continue to require one-use owner approval. CLI command
coverage and architecture are described in [CLI architecture](docs/CLI_ARCHITECTURE.md).

`devdrop tui` opens the interactive terminal dashboard. Use the sidebar or
`D`/`T`/`H` to navigate, `R` to refresh, `?` for help, and `Q` to exit. Pending
transfers always open an explicit review dialog before an approval decision.
The Transfers screen also shows PC-to-phone offers with server-reported bytes
sent; the backend does not expose incoming phone-upload progress.
Start the server first with `devdrop serve`; on a fresh install that command
offers the same HTTPS setup used by the legacy launcher and desktop GUI.
`devdrop tui` manages a running server and displays a specific TLS/configuration
error when it cannot connect.

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

HTTPS with explicitly provisioned trust now protects transport. Bearer sessions
and a separate one-use owner approval protect each transfer. See the
[transport trust model and limitations](docs/TRANSPORT.md); CA installation and
first trust are manual, and local processes remain inside the owner boundary.

Do not expose the DevDrop server directly to the public internet.

## Roadmap

Possible future improvements:

- Transfer progress
- Live device status
- Improved authentication
- Automated certificate lifecycle and onboarding
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

## Per-transfer approval

Every sender, including the desktop GUI, needs a fresh approval in addition to
its Bearer session. The process-local transfer service has a 120-second deadline
for both pending and approved requests. Restarting the backend loses all requests
and approvals; clients must pair/request again. Use one backend process/worker.

API (Bearer required except the local owner list/decisions):

- `POST /api/transfer-requests`: create with `type` (`file`, `text`, `link`),
  `sender`, `description`, optional `size`, and a content commitment.
- `GET /api/transfer-requests/{id}`: sender's own state only.
- `POST /api/transfer-requests/{id}/cancel`: sender cancellation.
- `GET /api/transfer-requests`: pending list, direct loopback owner only.
- `POST /api/transfer-requests/{id}/approve` or `/reject`: local owner decision;
  requires `Content-Type: application/json`. Browser Origin/Host must be local.
- Existing `POST /api/text` and `/api/upload` now additionally require
  `X-Transfer-ID: <approved request id>`. Missing/invalid sessions return 401;
  unavailable, unapproved, mismatched or reused permissions return 409.

Text/link commitments use SHA-256 of the exact UTF-8 `content` bytes; links use
`type: "link"` in the `/api/text` payload and are saved as text, never fetched or
opened. File commitments use an ordered `files` array of `{name, size, sha256}`;
its total size must match `size` when supplied. Multipart names and bytes must
match that manifest exactly. All hashes are lowercase hexadecimal. Names and
descriptions are sender claims, not verified identities or a content preview.

States are `pending -> approved/rejected/expired/cancelled`, with approved
requests also able to expire or be cancelled before use. `approved` plus
`used: true` records consumption without adding a new status. The lock makes
consumption atomic: only one sender can spend a permission, before filesystem
writes. A failed save spends it too; retry needs a new owner approval. A mismatch
does not spend a still-valid permission. Headers are checked before multipart
parsing; actual hashes are checked after receiving and before session-file writes.
An approved upload can still use temporary spool storage during verification.

The GUI displays pending claims and sends all network/hash/wait work for this
flow to background threads. Select a request and click Approve or Reject. GUI
file sends use the same flow and never auto-approve. The browser waits, polls
status and shows rejection/expiration; it hashes before requesting approval.
HTTPS and WebCrypto are now required; the HTTP SHA-256 fallback has been removed.
Browser hashing currently reads a whole file into memory, so very large files can
be expensive.

Limits: 100 files per request, 20 active requests per session, 1000 retained
requests total; terminal/used records are discarded one hour after their deadline.
Expiry frees active slots. All request memory is lost on restart. Loopback is the
existing owner trust boundary: another local process can make owner decisions.
This does not isolate OS users or provide persistent device trust, upload quotas,
or atomic transactions spanning saved files and SQLite history. The CLI
can list, approve and reject pending requests with `devdrop transfers`; the GUI
and local management API continue to use the same owner boundary.

## Required HTTPS setup

Both launchers now require provisioned TLS identities and refuse HTTP fallback.
See [transport setup and trust model](docs/TRANSPORT.md) before launching, including
phone CA installation, encrypted keys and certificate renewal.

## Send files from PC to phone

Pair the phone, match its session ID in the desktop's **Send to browser** section,
and offer a chosen file. On the phone use **Incoming files -> Accept -> Download**.
See [PC-to-browser behavior, APIs and limits](docs/PC_TO_BROWSER.md).

## Relay between paired phone browsers

On phone A choose one file and phone B's session under **Recipient**. The computer
owner must approve the relay; B must then **Accept -> Download**. A can follow or
cancel it in **Sending through this computer**. Existing **This computer** uploads
and PC-to-browser offers remain available. See [relay flow and limits](docs/RELAY.md).

For Release Candidate 1 PC/Android smoke checks, see
[the manual verification checklist](docs/RC1_MANUAL_VERIFICATION.md). Automated
tests cover API and loopback TLS behavior but do not claim real-device E2E
coverage.
