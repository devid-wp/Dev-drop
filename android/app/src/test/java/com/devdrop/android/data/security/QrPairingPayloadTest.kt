package com.devdrop.android.data.security

import com.devdrop.android.data.model.ConnectionException
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class QrPairingPayloadTest {
    private val certificate by lazy {
        javaClass.classLoader!!.getResourceAsStream("certs/devdrop-test-ca.pem")!!.use {
            ServerTrust.readCaCertificate(it.readBytes())
        }
    }

    private fun payload(caHash: String = certificate.sha256, address: String = "https://localhost:8765"): String =
        JSONObject().put("version", 1).put("url", address).put("state", "ready")
            .put("attempt_id", "attempt_1234567890abcdef")
            .put("token", "T".repeat(48)).put("expires_in", 120)
            .put("ca_certificate_der", java.util.Base64.getEncoder().encodeToString(certificate.der))
            .put("ca_sha256", caHash)
            .put("server_certificate_sha256", "a".repeat(64)).toString()

    @Test fun validQrCarriesPinnedHttpsIdentityAndSingleUseAttempt() {
        val parsed = QrPairingPayload.parse(payload())
        assertEquals("https://localhost:8765", parsed.address)
        assertEquals(certificate.sha256, parsed.caSha256)
        assertEquals("attempt_1234567890abcdef", parsed.attemptId)
        assertEquals(120, parsed.expiresIn)
    }

    @Test fun alteredFingerprintOrInsecureAddressIsRejected() {
        assertThrows(ConnectionException.FingerprintMismatch::class.java) {
            QrPairingPayload.parse(payload(caHash = "0".repeat(64)))
        }
        assertThrows(ConnectionException.InvalidAddress::class.java) {
            QrPairingPayload.parse(payload(address = "http://localhost:8765"))
        }
    }
}
