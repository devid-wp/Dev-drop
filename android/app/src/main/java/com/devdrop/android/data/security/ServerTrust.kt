package com.devdrop.android.data.security

import com.devdrop.android.data.model.ConnectionException
import java.io.ByteArrayInputStream
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

data class CaCertificate(val der: ByteArray, val sha256: String)

object ServerTrust {
    fun readCaCertificate(bytes: ByteArray): CaCertificate {
        val certificate = try {
            CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(bytes)) as X509Certificate
        } catch (_: Exception) {
            throw ConnectionException.InvalidCertificate
        }
        if (certificate.basicConstraints < 0) throw ConnectionException.InvalidCertificate
        try {
            certificate.checkValidity()
        } catch (_: Exception) {
            throw ConnectionException.InvalidCertificate
        }
        val der = certificate.encoded
        return CaCertificate(der, fingerprint(der))
    }

    fun normalizeFingerprint(value: String): String = value.filterNot(Char::isWhitespace)
        .replace(":", "").lowercase()

    fun fingerprint(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it) }

    fun requireMatchingFingerprint(certificate: CaCertificate, confirmed: String) {
        val normalized = normalizeFingerprint(confirmed)
        if (!normalized.matches(Regex("[a-f0-9]{64}")) || normalized != certificate.sha256) {
            throw ConnectionException.FingerprintMismatch
        }
    }

    /** Trusts only the explicitly verified CA. HttpsURLConnection keeps its default hostname verifier. */
    fun sslContext(caDer: ByteArray): SSLContext {
        val managers = trustManagers(caDer)
        return SSLContext.getInstance("TLS").apply { init(null, managers, null) }
    }

    internal fun trustManagers(caDer: ByteArray): Array<TrustManager> {
        val certificate = readCaCertificate(caDer)
        val anchors = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null)
            setCertificateEntry("devdrop-owner-ca", CertificateFactory.getInstance("X.509")
                .generateCertificate(ByteArrayInputStream(certificate.der)))
        }
        return TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(anchors) }.trustManagers
    }

    internal fun serverTrustManager(caDer: ByteArray): X509TrustManager =
        trustManagers(caDer).filterIsInstance<X509TrustManager>().firstOrNull()
            ?: throw ConnectionException.InvalidCertificate
}
