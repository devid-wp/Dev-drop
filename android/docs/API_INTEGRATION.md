# Android client API integration

The Android client implements UDP server discovery, QR-bound TLS identity,
owner-approved pairing, encrypted local session storage, authenticated
reconnect, Android-to-PC uploads, and PC-to-Android downloads with SHA-256
receipt confirmation. The protocol details below were checked against the
current FastAPI routes and `app/discovery.py`.

## Server discovery

The optional HTTP discovery route is `GET /api/discover`; it returns
`{"servers":[{"name":"…","ip":"…","port":8765,"url":"https://…","status":"Available"}]}`.
The backend's local discovery service also listens for UDP broadcast on port
8766. A query is JSON with `magic: "DEVDROP_DISCOVERY_V1"`,
`action: "discover"`, and a random nonce; the response must echo the nonce and
include name, IP and HTTPS port. Android uses the UDP protocol directly on port
8766. It requires the echoed nonce, uses the packet source IP instead of the
untrusted claimed `ip`, and validates the TCP port. Discovery is unauthenticated
metadata and is not proof of server identity. A scan result remains untrusted
until the CA and HTTPS hostname have been verified.

## Pairing and session token

The owner obtains a one-use payload from `GET /api/pairing/qr`. It contains the
HTTPS URL, a random QR token and window ID, expiry, DER CA certificate, CA
SHA-256, and leaf certificate SHA-256. The Android app checks the CA hash, then
performs TLS chain and hostname verification plus the QR leaf pin check before
sending the QR token. It posts a six digit phone display code, a separate
random 256-bit polling key, and device label to `POST /api/pairing/claims`.
That QR token is consumed atomically; the short code is only a human check.

The owner reviews `GET /api/pairing/requests`, enters the code displayed by
the phone and explicitly calls `POST /api/pairing/requests/{id}/approve`, or
rejects it. A mismatch is terminal. Android polls
`GET /api/pairing/claims/{id}` with `X-Pairing-Poll-Key`; the normal one-hour
Bearer session is returned once to that key, after approval. Keep the Bearer
token only in Android Keystore-backed app storage, never in URLs/logs, and send
it as `Authorization: Bearer <token>` on session APIs. Sessions can be revoked
by the owner through the local-only recipient-session revoke route or by the
phone through `DELETE /api/session`. A device name or discovery response is
never an authorization credential.

The old `/api/pairing-code` and `/api/pair` route remains for older clients
during migration; new Android builds use QR pairing.

## TLS identity and first trust

All app and transfer routes require HTTPS, and the backend refuses HTTP.
Android trusts only the CA encoded in the scanned QR, validates its declared
fingerprint, verifies the server chain, hostname/SAN, and leaf fingerprint,
and sends no credentials before those checks pass. QR trust is valid only when
the user scans the code shown on the trusted PC screen; remote QR images are
not an authenticated trust channel. LAN discovery is never a trust source.
The CA, server address, and Bearer token are encrypted with an Android
Keystore AES-GCM key. On reconnect, the app checks `/api/health`, then
validates the session with authenticated `GET /api/incoming-offers`; a 401
clears the token and requires a fresh owner-approved QR pairing.

### Android first connection

1. Start Dev-Drop on the PC and open its local Web Panel, TUI, or PySide6 GUI.
2. In Android, tap **Scan QR** and scan the live QR shown on the PC.
3. Check the phone's six digit number against the connection request on the
   PC. Enter the number on the PC and explicitly approve the phone. The number
   is not an authentication secret; the random QR and poll tokens provide
   protocol authorization.
4. If the QR expires or the owner rejects it, scan a fresh QR. Each file
   transfer still requires its separate computer-owner approval.

The Android app does not alter the phone's global CA store. Browser trust
behavior remains platform-specific; the Python GUI uses its explicit CA file.
No real Android connection is claimed based on Linux tests alone.

## Phone to PC upload and approval

Create one transfer with `POST /api/transfer-requests` using the Bearer token.
The request includes `type: "file"`, a sender label, description, total size,
and an ordered `files` array of `{name,size,sha256}`. The phone computes each
SHA-256 by streaming a ContentResolver URI, then reopens each URI for upload.
The local computer owner must approve this manifest. Poll
`GET /api/transfer-requests/{id}` as the same session until approved or
terminal; the approval is one-use and expires after two minutes. After approval
the app sends multipart `files` to `POST /api/upload` with
`Authorization: Bearer …` and `X-Transfer-ID: {id}`. The backend checks all
manifest names, lengths and SHA-256 values before saving and returns success
only after saving. Although the API accepts multiple manifest entries, its
filesystem writes are per file and it does not roll back earlier files if a
later save fails. Android therefore sends selections sequentially, with a
separate owner approval and one-use request for each file. Progress counts file
payload bytes actually written; completion is shown only after the server's
successful response. Cancellation closes active streams and the HTTPS
connection and attempts to cancel the current pending approval.

## PC to phone offers and downloads

`GET /api/incoming-offers` returns only offers bound to the caller's session.
Each offer now includes `sha256`, computed from the private snapshot when the
offer is created. This additive field lets a native client verify that the
streamed bytes match the exact offered snapshot without buffering the file.
Accept or reject using `POST /api/incoming-offers/{id}/accept` or `/reject`.
Accept sets a short-lived, one-use, secure, HttpOnly cookie scoped to that
offer's download path. Download with a normal HTTPS GET to
`/api/incoming-offers/{id}/download`; keep normal platform TLS validation and
send both the same session's Bearer authorization and the returned path-scoped
cookie. The server streams the file in chunks. Android writes the response to a
user-selected Storage Access Framework document, verifies Content-Length and
SHA-256 while writing, and removes the partial destination on cancellation or
failure. Only after the SAF output closes successfully, Android sends a
session-bound `POST /api/incoming-offers/{id}/receipt` containing the written
byte count and SHA-256. The backend checks the recipient session, exact size,
and snapshot digest before changing `sent` to `received`; an exact retry is
idempotent. Other sizes or digests, foreign sessions, and receipts before the
stream finishes are rejected. `GET /api/incoming-offers/{id}/state` exposes the
separate server `sent` and receiver `received` states. If saving succeeds but
the receipt request fails, Android keeps the verified file and offers a receipt
retry; it does not download or overwrite the file again.

## Phone to phone relay

`GET /api/relay-recipients` lists opaque recipient selectors. Create one-file
relay with `POST /api/relays`, binding the recipient ID and file manifest. The
computer owner approval is required before `POST /api/relays/{id}/upload` can
consume the one-use approval. The recipient separately accepts the resulting
incoming file offer and downloads it using the offer cookie flow above.
`GET /api/relays/{id}` reports relay lifecycle status to its sender session;
`POST /api/relays/{id}/cancel` cancels an eligible relay. The relay passes
through the computer and is not device-to-device transport.

## Progress semantics

For uploads, client-side request bytes and server-side validation/completion are
separate events. For downloads, Android reports bytes only after its SAF output
stream accepts each bounded chunk; speed and ETA appear after a real sample
interval. Completion requires exact Content-Length, matching SHA-256, and a
successful output close. The backend's `sent_bytes` describes bytes emitted by
the server, not local persistence. Incoming offers are polled while the
Transfers or Incoming screen is visible and the Activity is started. The
desktop owner's approval and the recipient's separate Accept action remain
distinct confirmations.
