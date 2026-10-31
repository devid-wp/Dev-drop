# CLI architecture and current coverage

The `devdrop` console entry point is `app.cli:main`. It adds a terminal command
surface without replacing the existing backend or PySide6 GUI. The older
`python devdrop.py` launcher and `devdrop.bat` GUI launcher remain available.

## Existing reusable logic

- `app.transport` loads the provisioned TLS identity, pins the server
  fingerprint, validates the CA and SAN, disables redirects, and exposes
  `open_local` for direct loopback HTTPS management requests.
- `app.discovery.DiscoveryService` implements the existing UDP discovery
  protocol. The CLI calls its `discover` method rather than inventing a second
  protocol.
- `app.config` loads and saves the non-secret port and session-root settings.
- `app.runtime` provides the local server bind host and timestamped session
  directory creation.
- `app.history_store.HistoryStore`, `app.transfer_requests.TransferService`,
  and the other backend services remain the owners of persistence and transfer
  approval rules. CLI management decisions go through the same FastAPI routes
  that the GUI uses, so local-only checks stay in `app.main`.

## Logic that remains in other interfaces

`devdrop_gui.py` contains its own `BackendClient`, Uvicorn thread lifecycle,
file hashing/upload progress, and Qt widgets. It performs desktop sends by
creating a Bearer session through the local pairing flow, requesting the
one-use approval, and uploading only after the owner approves. This work has
not been copied into the CLI. `app.main` remains the HTTP adapter that enforces
local-owner checks and connects requests to existing service objects.

## Commands

| Command | Status | Behavior |
|---|---|---|
| `devdrop --help` | Available | Lists supported command groups. |
| `devdrop version` | Available | Reports the CLI version. |
| `devdrop status` | Available | Reads local `/api/status`; omits the pairing code. |
| `devdrop serve` | Available | Starts the existing FastAPI app with the configured TLS identity and a new session folder. |
| `devdrop devices` | Available | Runs existing LAN UDP discovery. |
| `devdrop pair` | Available | Shows this computer's current pairing code for a phone/browser; it does not create a remote CLI session. |
| `devdrop transfers` | Available | Lists local pending owner requests; explicit `--approve ID` or `--reject ID` calls the local owner decision route. |
| `devdrop history` | Available | Reads existing local transfer history. |
| `devdrop config` | Available | Reads or writes only `session_root` and `port`. |
| `devdrop doctor` | Available | Checks TLS configuration, writable storage, port availability, and verified local HTTPS health. |
| `devdrop tui` | Available | Opens a full-screen dashboard over the same local APIs and discovery service. |
| `devdrop send` | Deferred | There is no secure CLI store for remote CA trust and Bearer sessions. Tokens are not accepted as command arguments or written to ordinary config. |
| Remote `devdrop pair` | Deferred | Remote pairing requires the same missing remote trust/session store. The current `pair` command displays the local host code only. |

JSON output is available for commands returning structured data. Exit code 0
means success, 1 is a local/configuration or command error, 2 is an argparse
usage error, and 3 means a local service or verified endpoint is unavailable.
Pairing codes are printed only by the explicit `pair` command. Bearer tokens,
key passwords, and transfer contents are not logged.

## Next application-service boundary

The TUI uses `TuiServices` as a thin facade over the existing local API helper,
`DiscoveryService`, `TLSSettings`, and config functions; it does not own backend
rules. Refreshes and decisions run in cancellable Textual workers, with short
request timeouts so shutdown can wait for in-flight work. The TUI reads real
`/api/outgoing-offers` byte counts for PC-to-phone streams. The backend does not
expose byte progress for incoming phone uploads, and the TUI reports that
limitation instead of fabricating a progress bar. Network and config work runs
in managed background threads with cancellation events, bounded requests, and
joins during shutdown.

No second abstraction layer is needed for current local commands: the CLI uses
the existing transport, config, discovery, runtime, store and domain services.
Before remote CLI sending is added, introduce a small remote client/session
service that accepts an independently verified CA/fingerprint, keeps token
material in an OS-protected credential store, and exposes pair, send and
approval-poll operations. The GUI's inline `BackendClient` and upload flow can
then migrate to that service without changing the HTTP contract. The TUI and
Web Panel should call these same application operations rather than implement
parallel transfer rules.
