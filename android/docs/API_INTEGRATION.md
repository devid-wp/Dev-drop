# Android client API integration plan

This Android milestone provides the native UI and local file selection only.
It does not make network requests, discover devices, pair, or simulate transfer
state. The existing backend is the protocol reference for a later integration.

## Server discovery

The HTTP discovery route is `GET /api/discover`; it returns
`{"servers":[{"name":"…","ip":"…","port":8765,"url":"https://…","status":"Available"}]}`.
The backend's local discovery service also listens for UDP broadcast on port
8766. A query is JSON with `magic: "DEVDROP_DISCOVERY_V1"`,
`action: "discover"`, and a random nonce; the response must echo the nonce and
include name, IP and HTTPS port. Discovery is unauthenticated metadata and is
not proof of server identity. Validate every response and require a subsequent
verified TLS connection before showing the server as trusted.

## Pairing and session token

The one-time pairing code is exposed only to a direct loopback owner by
`GET /api/pairing-code`; a phone receives it out-of-band from the computer
owner. Pair over HTTPS with `POST /api/pair` and JSON `{"code":"123456789"}`.
A successful response includes `{"paired":true,"token":"…"}`. Keep the
Bearer token only in private app storage, do not put it in a URL, logs, or
analytics, and send it as `Authorization: Bearer <token>` on session APIs.
The backend session currently expires after one hour; pairing again creates a
new session. A device name or discovery response is never an authorization
credential.

## TLS identity and first trust

All app and transfer routes require HTTPS, and the backend refuses HTTP; the
repository's trust setup uses a dedicated local CA. Android must validate the
certificate chain, validity period, and hostname/SAN against that CA before
sending a pairing code or token. The CA certificate and its SHA-256 fingerprint
must be provisioned to the phone through a trusted independent channel and
verified against the computer owner's display. Do not accept a certificate
fetched over unauthenticated LAN discovery, do not silently trust on first use,
and do not bypass hostname or chain errors. The network security configuration
and provisioning UI are intentionally not implemented yet; the app currently
has no network permission or cleartext opt-in.

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
