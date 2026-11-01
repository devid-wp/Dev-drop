# HTTPS transport: scope and setup

Dev-Drop now requires HTTPS everywhere, including desktop loopback traffic.
There is no HTTP listener, redirect bootstrap, certificate-warning exception,
automatic CA installation, or trust-on-first-use from the network. On first
server startup, missing TLS configuration can be prepared only after explicit
local consent; declining or invalid configuration refuses startup. Start via
`devdrop serve`, `devdrop.py`, or the desktop GUI. `devdrop tui` manages an
already-running server. Starting `uvicorn app.main:app` without TLS only returns
HTTP 426, never the app. Keep proxy headers disabled; a reverse proxy is outside
this stage's trust model.

## Choice of transport

| Approach | Browser / first-trust limits | Decision |
| --- | --- | --- |
| Self-signed HTTPS + fingerprint | A desktop/native client can pin before sending. A normal web page cannot inspect/pin the TLS certificate before loading. A self-signed warning alone does not establish identity or prevent MITM. | Not the mobile bootstrap. |
| HTTPS with a dedicated, locally trusted CA | Standard TLS, chain/date/SAN validation. Requires installing the verified CA on each phone/browser before connecting. | Implemented infrastructure. GUI also pins the exact leaf certificate. |
| Application encryption using Web Crypto | `crypto.subtle` needs a secure context; ordinary LAN HTTP is not one. HTTP-delivered JavaScript could be replaced, including its cryptography and key exchange. | Not an alternative bootstrap. No custom encryption protocol. |

Sources: [Web Crypto secure contexts](https://developer.mozilla.org/en-US/docs/Web/API/Crypto),
[Chrome local trust](https://chromium.googlesource.com/chromium/src/+/HEAD/net/data/ssl/chrome_root_store/faq.md),
[Firefox Android CA setting](https://bugzilla.mozilla.org/show_bug.cgi?id=1910173),
[Python TLS verification](https://docs.python.org/3.14/library/ssl.html),
[Uvicorn HTTPS options](https://uvicorn.dev/settings/).

## Provision certificates before starting

For managed deployments, use an existing trusted issuer or a dedicated private
CA managed outside Dev-Drop. On a local first run, `devdrop serve` offers to
create a dedicated local CA and loopback server identity after explicit consent.
It reuses existing CA/certificate files when present. By default, private keys
are PKCS#8 files protected by owner-only OS permissions (POSIX mode `0600`;
Windows owner and SYSTEM ACL). This protects against other local accounts, not
malware running as the same user. **Advanced Security Mode** encrypts the keys
with a user passphrase and asks for it at each start. Passwords stay in process
memory and are never stored in configuration or logs.

First-run setup uses the Python `cryptography` package, not an OpenSSL command
line tool. It writes `tls.json` at
`~/.config/DevDrop/tls.json`, with server files in `tls/` and the CA in `ca/`.
An earlier script put `tls.json` inside `tls/`; the application migrates that
config without replacing the CA, key, or certificate. A damaged config is
diagnosed and never silently replaced.

The automatic certificate contains loopback, `localhost`, the computer
hostname and current LAN IP addresses in its SAN. If a managed computer's LAN
address changes, DevDrop issues a new leaf certificate under the same CA and
retains the old certificate file; the CA trust anchor does not change. When
upgrading an earlier encrypted local identity, DevDrop can move the same keys to
owner-only OS storage after explicit consent, retaining encrypted originals.

For example, on a trusted/offline machine using OpenSSL (commands prompt for key
passwords; do not put production passwords in command arguments):

```text
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -aes-256-cbc -out ca-key.pem
openssl req -new -x509 -key ca-key.pem -sha256 -days 3650 -out ca.pem -subj "/CN=DevDrop Dedicated Local CA" -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -aes-256-cbc -out server-key.pem
openssl req -new -key server-key.pem -out server.csr -subj "/CN=DevDrop"
```

Create `server.ext`, replacing the LAN address with the computer's actual address:

```ini
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:127.0.0.1,IP:192.168.1.50,DNS:localhost
```

Then issue the server certificate:

```text
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -sha256 -days 90 -extfile server.ext -out server.pem
openssl x509 -in server.pem -noout -fingerprint -sha256
openssl x509 -in ca.pem -noout -fingerprint -sha256
```

Only `server.pem` (leaf first, then intermediates if needed), encrypted
`server-key.pem` and the public `ca.pem` belong on the server. Keep the CA private
key offline; never put it on a phone or distribute it. Neither key belongs in
Git, build artifacts or the web directory. Keep TLS files outside the session
root so they cannot appear in transfer counters/history or be deleted with a
session. On POSIX use owner-only storage and `chmod 600 server-key.pem` (enforced).
On Windows use an owner-only NTFS directory under the user's profile, remove
broad inherited access using Windows Security/Advanced permissions, and retain
only the owner and necessary system/admin access. Encryption is enforced on both
platforms; Windows ACL inspection/enforcement is manual in this stage. Protect
source copies and backups too; encryption does not protect a running process
from malware with the same user privileges.

Create `tls.json` under the usual DevDrop configuration directory:
`%APPDATA%/DevDrop` on Windows, otherwise `~/.config/DevDrop`. Alternatively set
`DEVDROP_TLS_CONFIG` to its path. Use absolute paths (JSON Windows backslashes must
be escaped, or use forward slashes):

```json
{
  "certificate": "C:/Users/OWNER/AppData/Roaming/DevDrop/tls/server.pem",
  "key": "C:/Users/OWNER/AppData/Roaming/DevDrop/tls/server-key.pem",
  "ca": "C:/Users/OWNER/AppData/Roaming/DevDrop/tls/ca.pem",
  "host": "192.168.1.50",
  "sha256": "REPLACE_WITH_64_HEX_DIGITS_OF_SERVER_CERTIFICATE_SHA256_WITHOUT_COLONS"
}
```

`host` is the LAN identity in the certificate SAN. The certificate must also have
IP SAN `127.0.0.1` for the GUI. The GUI uses a dedicated CA context, normal
hostname validation and the configured leaf pin *before* sending HTTP headers.
It ignores environment proxies and refuses redirects. Server startup verifies
the key/password, certificate chain, validity, SANs and leaf pin by an in-memory
TLS handshake. Both launchers configure Uvicorn for TLS, proxy headers disabled,
TLS 1.2 minimum (CPython secure server defaults), and modern ECDHE ciphers.

## First trusted phone connection

The native Android app does not require installing the local CA into Android's
global trust store. Scan the live QR from the trusted PC screen. The QR carries
the HTTPS address, public CA certificate, its SHA-256, the server leaf
fingerprint, and a one-use high-entropy pairing token. Android validates the CA
fingerprint and then checks the TLS chain, certificate hostname/SAN, and leaf
fingerprint before sending the pairing token. The phone displays a short code;
the owner enters it in the local Web Panel, TUI, or PySide6 GUI and explicitly
approves the request. The short code is a human comparison value, not an
authentication secret. The process expires after two minutes.

This trust bootstrap relies on scanning the code displayed on the intended PC.
Do not treat a QR copied from an untrusted remote source as authentic. Browsers
still use the operating system/browser trust store and may require the public
CA to be installed there; never bypass a certificate warning.

Android Chrome and other browsers do not automatically use the app's QR trust
bootstrap. Browser access may require installing the public CA in the relevant
OS/browser trust store; behavior varies by platform/version. No physical
Android/Windows browser verification has been performed by automated Linux
tests.

## Identity changes and remaining boundaries

QR/URL uses configured `host`, not an unchecked current IP. Prefer a DHCP
reservation or a stable locally resolvable DNS name included in SAN. With an IP
SAN, changing IP requires reissuing a certificate and updating host/pin. DNS
identity can survive an IP change if local name resolution and SAN still match.
Discovery remains unauthenticated metadata and advertises HTTPS only; the web
client refuses cross-origin discovery navigation. It is not a trust bootstrap.

Changing a server certificate causes the GUI pin check to refuse connection.
There is no automatic acceptance or HTTP fallback. Stop the server, verify the
replacement certificate out of band, update certificate/key/host and the leaf
pin, and restart. Renewals under the same trusted CA ordinarily need no phone CA
reinstallation; browsers verify CA/hostname/date, **not** the GUI's exact leaf
pin. A new CA requires a new trusted out-of-band installation/removal procedure.
CA/key compromise is not solved by pinning a web page: manage renewal/revocation
outside this application. CRL/OCSP automation is not implemented.

The server rejects any plaintext HTTP ASGI request before reading its body, but
cannot prevent someone using an unrelated HTTP client from putting a secret on
the wire. App clients never do that. Likewise, visiting an attacker-controlled
HTTP clone is outside the trusted HTTPS workflow. Do not start a plaintext proxy
or distribute a page over HTTP. No automatic LAN bootstrap in an untrusted network
is claimed. Keep single-process approvals, loopback owner trust and the existing
file/history atomicity limitations documented above.

Tests generate temporary test-only keys/certificates using OpenSSL CLI, exercise
verification failures and real loopback HTTPS uploads. No production identities
are generated, no trust store is changed, and no public-network listener is used.
