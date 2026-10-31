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

Create a transfer with `POST /api/transfer-requests` using the Bearer token. A
file request includes `type: "file"`, a sender label, description, total size,
and an ordered `files` array of `{name,size,sha256}`. The local computer owner
must approve the request. Poll `GET /api/transfer-requests/{id}` as the same
session until approved or terminal; approval is one-use and expires. Then send
multipart `files` to `POST /api/upload` with `Authorization: Bearer …` and
`X-Transfer-ID: {id}`. The backend checks manifest names, lengths and SHA-256
before saving. A future Android sender should stream a `ContentResolver` input
stream, calculate/report progress from bytes actually written to the request,
and treat the server's successful response as completion, not an upload
progress event alone.

## PC to phone offers and downloads

`GET /api/incoming-offers` returns only offers bound to the caller's session.
Accept or reject using `POST /api/incoming-offers/{id}/accept` or `/reject`.
Accept sets a short-lived, one-use, secure, HttpOnly cookie scoped to that
offer's download path. Download with a normal HTTPS GET to
`/api/incoming-offers/{id}/download`; keep normal platform TLS validation and
cookie handling. The server streams the file in chunks. `GET
/api/incoming-offers/{id}/state` returns server-sent byte count and status for
the authorized recipient session. Those bytes mean the server emitted response
data; they do not prove Android persisted the downloaded file. Use a streaming
download sink (for example, a SAF destination) if the native app later needs a
reliable local saved-byte count.

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
separate events. For downloads, server stream progress reports bytes emitted by
the server; it cannot report whether a browser or OS saved the file. An Android
implementation should report downloaded/saved bytes only when its own streaming
sink confirms writes. Polling can use a modest interval (about one second while
active, stopped when terminal); do not persist each chunk to SQLite. The desktop
owner's approval is a separate confirmation and must never be bypassed by the
mobile client.
