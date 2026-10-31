package com.devdrop.android.data.network

import com.devdrop.android.data.model.ConnectionException
import com.devdrop.android.data.security.ServerTrust
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.net.InetAddress
import java.security.KeyFactory
import java.security.KeyStore
import java.security.cert.CertificateFactory
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Base64
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class VerifiedHttpsClientTest {
    @Test fun existingHttpsRoutesWorkAndHostnameMismatchFailsBeforeCredentials() {
        val resources = javaClass.classLoader!!
        val ca = ServerTrust.readCaCertificate(resources.getResourceAsStream("certs/devdrop-test-ca.pem")!!.use { it.readBytes() })
        val serverCert = resources.getResourceAsStream("certs/devdrop-test-server.pem")!!.use {
            CertificateFactory.getInstance("X.509").generateCertificate(it)
        }
        val privateKeyPem = resources.getResourceAsStream("certs/devdrop-test-server-key.pk8")!!.use { it.readBytes().toString(Charsets.US_ASCII) }
        val privateKeyDer = Base64.getMimeDecoder().decode(privateKeyPem.lineSequence().filterNot { it.startsWith("-----") }.joinToString(""))
        val privateKey = KeyFactory.getInstance("RSA").generatePrivate(PKCS8EncodedKeySpec(privateKeyDer))
        val root = CertificateFactory.getInstance("X.509").generateCertificate(resources.getResourceAsStream("certs/devdrop-test-ca.pem"))
        val keyStore = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
            load(null)
            setKeyEntry("server", privateKey, "test-only".toCharArray(), arrayOf(serverCert, root))
        }
        val keyManagers = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()).apply {
            init(keyStore, "test-only".toCharArray())
        }
        val serverContext = SSLContext.getInstance("TLS").apply { init(keyManagers.keyManagers, null, null) }
        val server = serverContext.serverSocketFactory.createServerSocket(0, 4, InetAddress.getByName("127.0.0.1")) as javax.net.ssl.SSLServerSocket
        val seen = mutableListOf<Pair<String, String?>>()
        val worker = Thread {
            repeat(4) {
                val socket = server.accept() as javax.net.ssl.SSLSocket
                socket.use { peer ->
                    try {
                        peer.startHandshake()
                        val input = BufferedInputStream(peer.inputStream)
                        val headerBytes = readHeaders(input)
                        val headers = headerBytes.toString(Charsets.ISO_8859_1).split("\r\n")
                        val requestLine = headers.first()
                        val contentLength = headers.drop(1).firstOrNull { it.startsWith("content-length:", true) }
                            ?.substringAfter(':')?.trim()?.toIntOrNull() ?: 0
                        val requestBody = ByteArray(contentLength)
                        var offset = 0
                        while (offset < contentLength) {
                            val count = input.read(requestBody, offset, contentLength - offset)
                            if (count < 0) break
                            offset += count
                        }
                        val authorization = headers.drop(1).firstOrNull { it.startsWith("authorization:", true) }?.substringAfter(':')?.trim()
                        synchronized(seen) { seen += requestLine to authorization }
                        val (status, response) = when {
                            requestLine.startsWith("GET /api/health ") -> 200 to "{\"status\":\"ok\",\"app\":\"DevDrop\"}"
                            requestLine.startsWith("POST /api/pair ") -> {
                                synchronized(seen) { seen += "PAIR_BODY" to requestBody.toString(Charsets.UTF_8) }
                                200 to "{\"paired\":true,\"token\":\"unit-test-session-token-123456\"}"
                            }
                            requestLine.startsWith("GET /api/incoming-offers ") -> 200 to "{\"offers\":[],\"session_id\":\"test\"}"
                            else -> 404 to "{}"
                        }
                        val bytes = response.toByteArray()
                        peer.outputStream.write("HTTP/1.1 $status OK\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray(Charsets.US_ASCII))
                        peer.outputStream.write(bytes)
                        peer.outputStream.flush()
                    } catch (_: SSLException) {
                        // Expected for the last request, which deliberately uses a hostname absent from SAN.
                    }
                }
            }
        }.apply { isDaemon = true; start() }
        try {
            val client = DevDropHttpClient()
            val address = "https://localhost:${server.localPort}"
            client.health(address, ca.der)
            assertEquals("unit-test-session-token-123456", client.pair(address, ca.der, "123456789"))
            client.verifySession(address, ca.der, "unit-test-session-token-123456")
            assertThrows(ConnectionException.TlsIdentity::class.java) {
                client.health("https://127.0.0.1:${server.localPort}", ca.der)
            }
            synchronized(seen) {
                assertEquals(4, seen.size)
                val requests = seen.filterNot { it.first == "PAIR_BODY" }
                assertEquals(3, requests.size)
                assertEquals("GET /api/health HTTP/1.1", requests[0].first)
                assertNull(requests[0].second)
                assertEquals("{\"code\":\"123456789\"}", seen.first { it.first == "PAIR_BODY" }.second)
                assertNull(requests[1].second)
                assertEquals("GET /api/incoming-offers HTTP/1.1", requests[2].first)
                assertEquals("Bearer unit-test-session-token-123456", requests[2].second)
            }
            worker.join(2_000)
        } finally {
            server.close()
        }
    }

    private fun readHeaders(input: BufferedInputStream): ByteArray {
        val bytes = ByteArrayOutputStream()
        var state = 0
        while (bytes.size() < 16_384) {
            val value = input.read()
            if (value < 0) break
            bytes.write(value)
            state = when {
                state == 0 && value == '\r'.code -> 1
                state == 1 && value == '\n'.code -> 2
                state == 2 && value == '\r'.code -> 3
                state == 3 && value == '\n'.code -> 4
                value == '\r'.code -> 1
                else -> 0
            }
            if (state == 4) break
        }
        return bytes.toByteArray()
    }
}
