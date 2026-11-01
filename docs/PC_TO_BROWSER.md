# PC -> browser file offers

This direction uses the existing HTTPS server and Bearer sessions. It adds no
server, persistent device identity or phone-to-phone transport. Selecting a file,
recipient session and **Choose file and offer to browser** is the computer owner's
consent for that exact outgoing snapshot. The phone must separately Accept it.
Existing browser -> PC owner approvals remain unchanged.

## Using it

1. Complete HTTPS trust setup and pair the phone as before.
2. In the phone's **Incoming files** block, note **This browser: <short ID>**.
3. In the desktop's **Send to browser** section, select that session ID, click
   **Choose file and offer to browser**, and choose one file.
4. The phone displays name, size and sender. Accept reveals a **Download** link;
   tap it to use the browser's normal download mechanism. Reject transfers nothing.
5. The desktop polls offer states and can cancel pending or accepted offers.

Session ID is an opaque selector, not a credential. IP and User-Agent are only
hints (User-Agent can be spoofed); they do not authorize anything. The backend
binds the offer to the actual current Bearer session. Refreshing/pairing again
creates a different session; old offers do not move to it automatically. The
session selector also includes desktop-created sessions; match the phone's ID.

## API

All requests require HTTPS. Owner endpoints additionally require the existing
direct-loopback/Origin/Host checks; mutations require JSON Content-Type.

| Method / path | Authorization / purpose |
| --- | --- |
| `GET /api/recipient-sessions` | Local owner: active sessions, opaque IDs, peer/agent hints; never tokens |
| `POST /api/outgoing-offers` | Local owner: `{path, recipient_id}` creates an offer from a chosen file |
| `GET /api/outgoing-offers` | Local owner: outgoing statuses, without source paths |
| `POST /api/outgoing-offers/{id}/cancel` | Local owner: cancel before streaming starts |
| `GET /api/incoming-offers` | Bearer: only that session's offers and its display ID |
| `POST /api/incoming-offers/{id}/accept` | Bearer: accept once and receive a scoped download cookie |
| `POST /api/incoming-offers/{id}/reject` | Bearer: reject a pending offer |
| `POST /api/incoming-offers/{id}/receipt` | Bearer: confirm a fully sent offer using exact size and SHA-256 |
| `GET /api/incoming-offers/{id}/download` | Scoped one-use cookie, with the original session still valid |
| `DELETE /api/session` | Bearer: revoke only the caller's current session |

`DELETE /api/session` revokes only the authenticated caller's current Bearer
session. Android uses it best-effort on Disconnect after clearing local
credentials. Pending, accepted, and active offers for that session are cancelled
and their snapshots removed. Completed `sent` offers remain available for a
verified receipt. If the phone is offline, server-side authorization remains
valid until the one-hour session expiry; restart also clears process-local
sessions.

Download accepts only an offer ID, never a caller-supplied file path. Arbitrary
query parameters cannot select another file. Paths can be registered only by the
local owner; remote callers cannot use this route even with a valid Bearer token.
Invalid offer state/access returns 409; normal Bearer failures return 401.

## Native download authorization

A normal navigation/download link cannot attach JavaScript's Authorization
header. Fetching a Blob would buffer the entire file in the browser. Instead,
the authorized Accept call sets a random, file-specific, short-lived cookie:
`Secure; HttpOnly; SameSite=Strict`, host-only, and restricted to this offer's
exact download path. The server retains only its SHA-256, tied to the receiving
session. It is neither the main Bearer token nor a general API credential. Neither
credential is put in a URL, localStorage or logs. JavaScript never reads the
cookie. A supplied Bearer header must also match the recipient session.

A valid cookie atomically reserves the accepted offer before any bytes are sent.
A simultaneous second request loses; replay, cancellation, expiry and expired
sessions fail. The response clears the cookie. As with any credential, someone
who steals the download cookie can exercise its narrow authority; tabs within
one browser profile share cookies, and are not isolated security principals.
No browser cookie can provide isolation from same-origin script compromise.

Downloads are attachments (`application/octet-stream`, safe UTF-8 filename,
`nosniff`, `no-store`) streamed in 256-KiB chunks. The web client never fetches the
file body or builds a Blob. Accept and Download are separate user clicks to avoid
relying on retained user activation after an asynchronous request. Save location,
filename adjustments, whether a preview opens, and download UI depend on the
mobile browser. Physical Android browser behavior is not covered by Linux tests.

## Snapshot and lifecycle

The service uses a private temporary directory, not the user's session folder or
web directory. It copies the selected regular readable file to a random snapshot
using bounded reads; symlinks and directories are refused. It rejects a source
whose size/mtime changed during copying. This isolates a finished offer from
later edits/deletion of the original file. Source paths are never returned.
Copying runs in FastAPI's worker thread and the desktop request runs in a
background thread, leaving the Qt event loop free. The owner can still choose
sensitive files intentionally: loopback processes remain within the existing
owner trust boundary.

Offers live for five minutes in one backend process. Native Android can progress
through `pending -> accepted -> streaming -> sent -> received` by posting a
verified receipt; browser downloads currently stop at `sent`. Pending can become
rejected, and pending/accepted can become cancelled or expired. Once streaming starts,
cancellation, retry and range/resume are not supported. A failed/interrupted
attempt spends the offer and needs a fresh offer. `sent` means the server finished
streaming, not proof the phone saved the file. Android sends a receipt only
after verifying the full content and closing its SAF destination. The server
changes `sent` to `received` only for the offer's recipient session and the
exact snapshot size and SHA-256. An exact receipt retry is idempotent. Other
values, foreign sessions, and acknowledgments before streaming finishes are
rejected. Connection teardown closes the file and removes the snapshot,
including on disconnect.

Expired, rejected and cancelled snapshots are removed on service activity;
shutdown cleans managed temporary storage. State is lost on restart; a hard crash
can leave private temporary files requiring manual cleanup. There is a cap of
100 retained/preparing offers; terminal records expire one hour after their
deadline. There is no disk-byte quota or copy-progress UI. Snapshots require extra
disk space; a timed-out desktop creation request may still finish on the server,
so check the outgoing list before retrying. An offer cannot be cancelled during
its preparation. Outgoing transfers do not yet add history entries to the
incoming-transfer SQLite history. TLS/CA lifecycle and loopback-owner limitations
from TRANSPORT.md still apply.
