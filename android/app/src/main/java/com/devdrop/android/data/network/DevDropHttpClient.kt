package com.devdrop.android.data.network

import com.devdrop.android.data.model.ConnectionException
import com.devdrop.android.data.security.ServerTrust
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.Proxy
import java.net.URL
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLException

class DevDropHttpClient {
    fun health(address: String, caDer: ByteArray) {
        val body = request(address, "/api/health", caDer, null, "GET", null)
        val response = FlatJson.parse(body.toString(Charsets.UTF_8)) ?: throw ConnectionException.InvalidServerResponse
        if (response["status"] != "ok" || response["app"] != "DevDrop") {
            throw ConnectionException.InvalidServerResponse
        }
    }

    fun pair(address: String, caDer: ByteArray, code: String): String {
        val body = "{\"code\":\"$code\"}".toByteArray(Charsets.UTF_8)
        val response = FlatJson.parse(request(address, "/api/pair", caDer, null, "POST", body).toString(Charsets.UTF_8))
            ?: throw ConnectionException.InvalidServerResponse
        val token = response["token"]
        if (response["paired"] != "true" || token.isNullOrBlank() || token.length !in 16..256) {
            throw ConnectionException.InvalidServerResponse
        }
        return token
    }

    fun verifySession(address: String, caDer: ByteArray, token: String) {
        request(address, "/api/incoming-offers", caDer, token, "GET", null, readBody = false)
    }

    private fun request(
        address: String,
        path: String,
        caDer: ByteArray,
        token: String?,
        method: String,
        body: ByteArray?,
        readBody: Boolean = true,
    ): ByteArray {
        val base = ServerAddress.normalize(address) ?: throw ConnectionException.InvalidAddress
        var connection: HttpsURLConnection? = null
        try {
            connection = URL(base + path).openConnection(Proxy.NO_PROXY) as? HttpsURLConnection
                ?: throw ConnectionException.InvalidAddress
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 5_000
            connection.readTimeout = 5_000
            connection.useCaches = false
            connection.requestMethod = method
            connection.sslSocketFactory = ServerTrust.sslContext(caDer).socketFactory
            connection.hostnameVerifier = HttpsURLConnection.getDefaultHostnameVerifier()
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("User-Agent", "Dev-Drop-Android/${com.devdrop.android.BuildConfig.VERSION_NAME}")
            if (token != null) connection.setRequestProperty("Authorization", "Bearer $token")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.setFixedLengthStreamingMode(body.size)
                connection.outputStream.use { it.write(body) }
            }
            val status = connection.responseCode
            if (status !in 200..299) {
                connection.errorStream?.close()
                throw mapHttpError(status, token != null, method == "POST" && path == "/api/pair")
            }
            if (!readBody) {
                connection.inputStream.close()
                return byteArrayOf()
            }
            return connection.inputStream.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    if (output.size() + count > MAX_RESPONSE_BYTES) throw ConnectionException.InvalidServerResponse
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            }
        } catch (error: ConnectionException) {
            throw error
        } catch (error: SSLException) {
            throw mapNetworkError(error)
        } catch (error: SocketTimeoutException) {
            throw mapNetworkError(error)
        } catch (error: IOException) {
            throw mapNetworkError(error)
        } finally {
            connection?.disconnect()
        }
    }

    private companion object { const val MAX_RESPONSE_BYTES = 64 * 1024 }
}

internal fun mapHttpError(status: Int, authenticated: Boolean, pairingRequest: Boolean): ConnectionException = when {
    status == 401 && authenticated -> ConnectionException.SessionExpired
    status == 401 && pairingRequest -> ConnectionException.InvalidPairingCode
    else -> ConnectionException.HttpFailure(status)
}

internal fun mapNetworkError(error: Throwable): ConnectionException = when (error) {
    is SSLException -> ConnectionException.TlsIdentity
    is IOException, is SocketTimeoutException -> ConnectionException.NetworkUnavailable
    else -> ConnectionException.NetworkUnavailable
}
