package com.devdrop.android.data.model

data class DiscoveredServer(val name: String, val address: String)

data class TrustedConnection(
    val address: String,
    val caCertificateDer: ByteArray,
    val caSha256: String,
    val token: String,
    val serverName: String = "Dev-Drop server",
)

enum class ConnectionPhase {
    Disconnected,
    Scanning,
    NoDevices,
    ServersFound,
    PairingRequired,
    Connecting,
    Connected,
    Unavailable,
    Error,
}

data class ConnectionUiState(
    val phase: ConnectionPhase = ConnectionPhase.Disconnected,
    val servers: List<DiscoveredServer> = emptyList(),
    val addressDraft: String = "",
    val selectedCaDer: ByteArray? = null,
    val selectedCaSha256: String? = null,
    val selectedCaAddress: String? = null,
    val fingerprintConfirmation: String = "",
    val pairingCode: String = "",
    val qrPairing: Boolean = false,
    val qrAttemptId: String? = null,
    val qrToken: String? = null,
    val qrServerFingerprint: String? = null,
    val connectedAddress: String? = null,
    val connectedName: String? = null,
    val trustedFingerprint: String? = null,
    val errorMessage: String? = null,
)

sealed class ConnectionException(message: String) : Exception(message) {
    data object InvalidAddress : ConnectionException("Enter an HTTPS address such as https://192.168.1.50:8765.")
    data object InvalidCertificate : ConnectionException("The selected file is not a valid CA certificate.")
    data object FingerprintMismatch : ConnectionException("The CA fingerprint does not match the value verified with the server owner.")
    data object TlsIdentity : ConnectionException("TLS trust or server hostname verification failed. Check the CA, address, and certificate SAN.")
    data object NetworkUnavailable : ConnectionException("The server could not be reached. Check the address and local network.")
    data object InvalidPairingCode : ConnectionException("Pairing code is invalid or expired. Ask the computer owner for the current code.")
    data object PairingExpired : ConnectionException("The QR pairing expired. Scan a fresh code from the computer.")
    data object PairingRejected : ConnectionException("The computer owner rejected this connection request.")
    data object SessionExpired : ConnectionException("The session expired. Pair this device again.")
    data class HttpFailure(val status: Int) : ConnectionException("The server returned HTTP $status.")
    data object InvalidServerResponse : ConnectionException("The server response was not a valid Dev-Drop response.")
}

fun reduceConnectionPhase(current: ConnectionPhase, event: ConnectionEvent): ConnectionPhase = when (event) {
    ConnectionEvent.Search -> ConnectionPhase.Scanning
    ConnectionEvent.NoneFound -> ConnectionPhase.NoDevices
    ConnectionEvent.Found -> ConnectionPhase.ServersFound
    ConnectionEvent.SelectServer -> ConnectionPhase.PairingRequired
    ConnectionEvent.Connect -> ConnectionPhase.Connecting
    ConnectionEvent.Connected -> ConnectionPhase.Connected
    ConnectionEvent.Disconnected -> ConnectionPhase.Disconnected
    ConnectionEvent.Unavailable -> ConnectionPhase.Unavailable
    ConnectionEvent.Failed -> ConnectionPhase.Error
    ConnectionEvent.SearchCancelled -> if (current == ConnectionPhase.Scanning) ConnectionPhase.Disconnected else current
}

enum class ConnectionEvent { Search, NoneFound, Found, SelectServer, Connect, Connected, Disconnected, Unavailable, Failed, SearchCancelled }
