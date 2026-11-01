# Phone -> PC -> phone relay

Relay uses the same HTTPS server, Bearer sessions, owner approval service and
browser file offers. It is not P2P, and adds no device trust or separate server.
This stage supports **one file per relay**. A group of files needs separate
requests and separate owner approvals.

## Workflow

1. Pair both phones over trusted HTTPS. Note phone B's short session ID in its
   Incoming files block.
2. On phone A, select File and choose B's session in Recipient (This computer
   retains the existing incoming-upload behavior).
3. A creates a relay request. The desktop owner sees its file metadata, canonical
   sender-session prefix and bound recipient-session prefix; Approve is required.
4. A uploads multipart data to the existing server. The server checks SHA-256,
   size, file name and session, spends the approval once, and copies the verified
   server-owned upload stream into the existing private file-offer store.
5. Only after copying and checking that the relay is still active is the offer
   published to B. No file bytes are delivered to B yet.
6. B can Reject or Accept, then Download. The existing scoped, one-use HTTPS
   cookie and native browser download are reused. A polls the relay state and
   can cancel it.

Recipient choices contain only opaque session IDs, never tokens, IPs or browser
headers. Short labels help match sessions; they are not trusted device names.
Only other sessions with valid authorization appear. A valid session does not
prove that its tab is still online: there is no presence protocol. Desktop-made
sessions can also appear, so match B's displayed ID. Reload/re-pairing creates a
new session and does not move existing relays to it.

## Routes

All routes use the existing Bearer dependency and HTTPS requirement:

| Method / route | Purpose |
| --- | --- |
| `GET /api/relay-recipients` | Other currently authorized sessions, IDs only |
| `POST /api/relays` | Create with the usual file manifest plus `recipient_id` |
| `GET /api/relays` | Sender's relay list |
| `GET /api/relays/{id}` | State for that relay's sender or recipient only |
| `POST /api/relays/{id}/upload` | One multipart file after owner approval |
| `POST /api/relays/{id}/cancel` | Sender cancellation |

The relay ID reuses its unique owner-approval request ID. The recipient is bound
at creation to an actual session, not accepted again from upload parameters.
Approval metadata includes `recipient_id`; ordinary `/api/text` and `/api/upload`
refuse such permissions. The ordinary approval-creation endpoint also refuses
relay recipients: relay orchestration must create the request. File hashes,
size, name, sender session and recipient binding are checked at consumption.
The header gate rejects unapproved/replayed relay uploads before multipart
parsing, and validation is repeated after parsing/hashing to cover races.

## State, races and cancellation

Typical states: `pending -> approved -> uploading -> offered -> accepted ->
streaming -> sent`. Rejection, cancellation, expiry and failure are terminal.
The existing approval lasts two minutes from its creation. The relay has a
five-minute total deadline; the recipient offer cannot extend it. Uploads must
finish validation before the approval expires, and copying/publication must fit
the relay deadline. For a relay, expiry also stops subsequent download reads.

A lock serializes state changes and one-use consumption; disk copying runs
outside it. A prepared snapshot is hidden from incoming lists and cannot be
accepted before publication. Cancellation during upload/copy marks the relay
revoked and discards the prepared snapshot instead of publishing. Concurrent
upload attempts create at most one offer. A failed upload/copy spends approval
and needs a fresh request.

After publication, cancellation revokes the existing offer/cookie. Relay streams
check cancellation/expiry between bounded chunks and stop further reads, including
when already streaming. Bytes already sent or buffered cannot be recalled. A
sender cannot cancel another sender's relay. B uses Reject for its pending offer;
the desktop owner can also cancel the published offer through existing controls.
Native downloads do not support resume/retry: a failed stream spends the offer.
`sent` describes the server stream. Android may advance its offer to `received`
after the SAF file is closed and its size and SHA-256 are verified; browser
downloads stay `sent` because they do not post a receipt.

## Temporary storage and limits

Multipart data uses FastAPI's existing spooled upload handling. A bounded copy
then enters FileOfferService's private temporary directory (random filenames,
safe display names). Relay never writes to the user's session/inbox directory,
never accepts paths from a phone, and never buffers a whole file in server RAM.
It reuses 256-KiB offer copying and streaming and the existing bounded manifest
hashing. Multipart spools are closed by the request lifecycle. Offer snapshots
are removed on rejection, cancellation, expiry or stream completion/disconnect;
expiry cleanup occurs on service activity. Normal shutdown cleans the managed
directory. A hard crash can leave temporary files requiring manual cleanup.

State is process-local and lost on restart; run one backend process. There are
at most 100 retained relay records and the existing 100 retained/preparing offer
slots, with terminal records retained up to an hour after their deadlines. There
is no disk-byte quota, resumable transfer or reliable online-presence check.
Browser hashing still uses a full file ArrayBuffer, as in the existing upload
client; this stage only guarantees bounded server memory. Relay is not recorded
in the incoming-file SQLite history and does not change inbox counters.

TLS validation, CA onboarding, loopback-owner trust, scoped-cookie security and
same-browser-profile limitations remain as documented in TRANSPORT.md and
PC_TO_BROWSER.md. No primary token or download grant is put in a URL. Physical
phone/browser testing remains separate from automated loopback HTTPS tests.
