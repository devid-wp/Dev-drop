# Android client API integration

The Android M1 client implements real UDP server discovery, HTTPS health checks,
CA-verified pairing, encrypted local session storage, authenticated session
checks, reconnect, and disconnect. File transfer is a later milestone. The
protocol details below were checked against the current FastAPI routes and
`app/discovery.py`.

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

The existing desktop QR payload contains only the configured HTTPS base URL; it
does not contain the pairing code or a trust credential. The 9-digit pairing
code is exposed only to a direct loopback owner by
`GET /api/pairing-code`; a phone receives it out-of-band from the computer
owner. Pair over HTTPS with `POST /api/pair` and JSON `{"code":"123456789"}`.
A successful response includes `{"paired":true,"token":"…"}`. Keep the
Bearer token only in private app storage, do not put it in a URL, logs, or
analytics, and send it as `Authorization: Bearer <token>` on session APIs.
The backend session currently expires after one hour; pairing again creates a
new session. The current backend does not consume or rotate the code after a
successful pairing, so it remains reusable until its five-minute expiry or
owner regeneration. A device name or discovery response is never an
authorization credential.

## TLS identity and first trust

All app and transfer routes require HTTPS, and the backend refuses HTTP; the
repository's trust setup uses a dedicated local CA. Android must validate the
certificate chain, validity period, and hostname/SAN against that CA before
sending a pairing code or token. The CA certificate and its SHA-256 fingerprint
must be provisioned to the phone through a trusted independent channel and
verified against the computer owner's display. Do not accept a certificate
fetched over unauthenticated LAN discovery, do not silently trust on first use,
and do not bypass hostname or chain errors. The Android app lets the user select
the public CA certificate with the Storage Access Framework, displays its
SHA-256, and requires an exact manual match with the independently obtained
fingerprint before pairing. Its TLS context trusts only that CA and retains
platform hostname/SAN verification. Trust material is never fetched from LAN
discovery. The CA, server address, and Bearer token are encrypted with an
Android Keystore AES-GCM key. On reconnect, the app checks `/api/health`, then
validates the session with authenticated `GET /api/incoming-offers`; a 401
clears the token and requires pairing again.

### Android first connection

1. Obtain the public CA certificate and its SHA-256 fingerprint over a trusted
   independent channel, such as USB. The fingerprint must be checked against
   the computer owner's trusted display.
2. In Dev-Drop Android, scan the QR or enter the configured HTTPS address. The
   QR contains only the URL. Select the CA certificate and compare its displayed
   SHA-256 to the independently obtained owner value. Never use an unverified
   certificate or fingerprint.
3. Enter the current 9-digit pairing code shown by the computer owner. The app
   sends it only after certificate-chain and hostname/SAN validation. The code
   expires in five minutes but the backend does not consume it after pairing;
   the owner should regenerate it after onboarding the intended device. Each
   file transfer still requires its separate computer-owner approval.

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
failure. `GET /api/incoming-offers/{id}/state` returns server-sent byte count and status for
the authorized recipient session. Those bytes mean the server emitted response
data; they do not prove Android persisted the downloaded file. Android reports
completion locally only after the stream hash matches and the SAF output closes
successfully. The backend still has no client receipt acknowledgement, so its
`sent` state is not proof of local persistence. A future compatible extension
could add a session-bound `POST /api/incoming-offers/{id}/receipt` with the
verified byte count and digest, recorded separately from server stream status.

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
