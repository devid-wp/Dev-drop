package com.devdrop.android.data.security

import com.devdrop.android.data.model.ConnectionException
import com.devdrop.android.data.network.ServerAddress
import org.json.JSONObject

data class QrPairingPayload(
    val address: String,
    val attemptId: String,
    val token: String,
    val expiresIn: Int,
    val caDer: ByteArray,
    val caSha256: String,
    val serverCertificateSha256: String,
) {
    companion object {
        fun parse(value: String): QrPairingPayload {
            val json = try { JSONObject(value) } catch (_: Exception) {
                throw ConnectionException.InvalidServerResponse
            }
            if (json.optInt("version", -1) != 1 || json.optString("state") != "ready") {
                throw ConnectionException.InvalidServerResponse
            }
            val address = ServerAddress.normalize(json.optString("url")) ?: throw ConnectionException.InvalidAddress
            val attemptId = json.optString("attempt_id")
            val token = json.optString("token")
            val expiry = json.optInt("expires_in", 0)
            val caDer = try { java.util.Base64.getDecoder().decode(json.getString("ca_certificate_der")) }
                catch (_: Exception) { throw ConnectionException.InvalidCertificate }
            val ca = ServerTrust.readCaCertificate(caDer)
            val declaredCa = json.optString("ca_sha256").lowercase()
            val leaf = json.optString("server_certificate_sha256").lowercase()
            if (ca.sha256 != declaredCa) throw ConnectionException.FingerprintMismatch
            if (!attemptId.matches(Regex("[A-Za-z0-9_-]{16,100}")) || token.length < 40 || token.length > 200 ||
                expiry !in 1..120 || !leaf.matches(Regex("[a-f0-9]{64}"))) {
                throw ConnectionException.InvalidServerResponse
            }
            return QrPairingPayload(address, attemptId, token, expiry, ca.der, ca.sha256, leaf)
        }
    }
}
