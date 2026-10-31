package com.devdrop.android.data.security

import com.devdrop.android.data.model.ConnectionException
import java.security.cert.CertificateFactory
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Test

class ServerTrustTest {
    private fun testCa(): CaCertificate {
        val cert = javaClass.classLoader!!.getResourceAsStream("certs/devdrop-test-ca.pem")!!.use {
            ServerTrust.readCaCertificate(it.readBytes())
        }
        return cert
    }

    @Test fun parsesCaAndRequiresTheOwnersOutOfBandFingerprint() {
        val ca = testCa()
        assertEquals(64, ca.sha256.length)
        assertEquals(ca.sha256, ServerTrust.normalizeFingerprint(ca.sha256.chunked(2).joinToString(":")))
        ServerTrust.requireMatchingFingerprint(ca, ca.sha256)
        assertThrows(ConnectionException.FingerprintMismatch::class.java) {
            ServerTrust.requireMatchingFingerprint(ca, "0".repeat(64))
        }
    }

    @Test fun tlsContextUsesExplicitCaTrustAnchor() {
        val context = ServerTrust.sslContext(testCa().der)
        assertEquals("TLS", context.protocol)
        assertNotNull(context.socketFactory)
    }

    @Test fun rejectsLeafCertificateAsCa() {
        val leaf = javaClass.classLoader!!.getResourceAsStream("certs/devdrop-test-leaf.pem")!!.use { it.readBytes() }
        assertThrows(ConnectionException.InvalidCertificate::class.java) { ServerTrust.readCaCertificate(leaf) }
    }

    @Test fun serverCertificateMustChainToTheSelectedCa() {
        val leaf = javaClass.classLoader!!.getResourceAsStream("certs/devdrop-test-server.pem")!!.use {
            CertificateFactory.getInstance("X.509").generateCertificate(it) as X509Certificate
        }
        ServerTrust.serverTrustManager(testCa().der).checkServerTrusted(arrayOf(leaf), "RSA")
        val wrongCa = javaClass.classLoader!!.getResourceAsStream("certs/devdrop-test-other-ca.pem")!!.use {
            ServerTrust.readCaCertificate(it.readBytes())
        }
        assertThrows(CertificateException::class.java) {
            ServerTrust.serverTrustManager(wrongCa.der).checkServerTrusted(arrayOf(leaf), "RSA")
        }
    }
}
