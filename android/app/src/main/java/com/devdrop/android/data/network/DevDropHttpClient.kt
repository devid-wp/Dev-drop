package com.devdrop.android.data.network

import com.devdrop.android.data.model.ConnectionException
import com.devdrop.android.data.model.IncomingFileOffer
import com.devdrop.android.data.security.ServerTrust
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.URLEncoder
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject
import java.net.SocketTimeoutException
import java.net.Proxy
import java.net.URL
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLException

class DevDropHttpClient {
    @Volatile private var activeConnection: HttpsURLConnection? = null
    @Volatile private var activeDownloadConnection: HttpsURLConnection? = null

    fun cancelActiveRequest() { activeConnection?.disconnect() }
    fun cancelActiveDownload() { activeDownloadConnection?.disconnect() }

    fun createFileRequest(address: String, caDer: ByteArray, token: String, files: List<UploadSource>): String {
        val manifest = JSONArray()
        files.forEach { manifest.put(JSONObject().put("name", it.name).put("size", it.size).put("sha256", it.sha256)) }
        val body = JSONObject().put("type", "file").put("sender", "Android device")
            .put("description", if (files.size == 1) files[0].name else "${files.size} files")
            .put("size", files.sumOf { it.size }).put("files", manifest).toString().toByteArray(Charsets.UTF_8)
        val response = request(address, "/api/transfer-requests", caDer, token, "POST", body)
        return JSONObject(response.toString(Charsets.UTF_8)).getString("id")
    }

    fun transferState(address: String, caDer: ByteArray, token: String, id: String): String {
        val response = request(address, "/api/transfer-requests/${URLEncoder.encode(id, "UTF-8")}", caDer, token, "GET", null)
        return JSONObject(response.toString(Charsets.UTF_8)).getString("status")
    }

    fun cancelTransfer(address: String, caDer: ByteArray, token: String, id: String) {
        request(address, "/api/transfer-requests/${URLEncoder.encode(id, "UTF-8")}/cancel", caDer, token, "POST", "{}".toByteArray())
    }

    fun uploadFiles(address: String, caDer: ByteArray, token: String, id: String, files: List<UploadSource>,
                    progress: (Long) -> Unit) {
        val boundary = "DevDrop-${java.util.UUID.randomUUID()}"
        val base = ServerAddress.normalize(address) ?: throw ConnectionException.InvalidAddress
        var connection: HttpsURLConnection? = null
        try {
            connection = URL("$base/api/upload").openConnection(Proxy.NO_PROXY) as HttpsURLConnection
            activeConnection = connection
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 10_000; connection.readTimeout = 30_000; connection.useCaches = false
            connection.requestMethod = "POST"; connection.doOutput = true
            connection.sslSocketFactory = ServerTrust.sslContext(caDer).socketFactory
            connection.hostnameVerifier = HttpsURLConnection.getDefaultHostnameVerifier()
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("X-Transfer-ID", id)
            connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            connection.setChunkedStreamingMode(64 * 1024)
            connection.outputStream.use { raw ->
                val out = CountingOutputStream(raw, progress)
                files.forEach { file ->
                    val quotedName = file.name.replace("\\", "\\\\").replace("\"", "\\\"")
                    out.write("--$boundary\r\nContent-Disposition: form-data; name=\"files\"; filename=\"$quotedName\"\r\nContent-Type: ${file.mimeType ?: "application/octet-stream"}\r\n\r\n".toByteArray(Charsets.UTF_8))
                    out.countPayload = true
                    file.open().use { input -> input.copyTo(out, 64 * 1024) }
                    out.countPayload = false
                    out.write("\r\n".toByteArray())
                }
                out.write("--$boundary--\r\n".toByteArray()); out.flush()
            }
            val status = connection.responseCode
            if (status !in 200..299) {
                val error = mapHttpError(status, true, false)
                if (status == 409) throw TransferFailure("approval", "Approval expired, was refused, or was already consumed.")
                if (status == 507) throw TransferFailure("storage", "The computer does not have enough free space.")
                throw error
            }
            val response = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            if (response.optBoolean("success") != true) throw ConnectionException.InvalidServerResponse
        } catch (error: ConnectionException) { throw error
        } catch (error: TransferFailure) { throw error
        } catch (error: Exception) { if (error is java.util.concurrent.CancellationException) throw error else throw mapNetworkError(error)
        } finally { activeConnection = null; connection?.disconnect() }
    }

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

    fun incomingOffers(address: String, caDer: ByteArray, token: String): List<IncomingFileOffer> {
        val body = request(address, "/api/incoming-offers", caDer, token, "GET", null)
        val offers = JSONObject(body.toString(Charsets.UTF_8)).optJSONArray("offers")
            ?: throw ConnectionException.InvalidServerResponse
        return buildList {
            for (index in 0 until offers.length()) {
                val item = offers.optJSONObject(index) ?: throw ConnectionException.InvalidServerResponse
                val identity = item.optString("id")
                val filename = item.optString("filename")
                val size = item.optLong("size", -1L)
                val hash = item.optString("sha256")
                if (!identity.matches(Regex("[A-Za-z0-9_-]{8,128}")) || filename.isBlank() || size < 0 ||
                    !hash.matches(Regex("[a-fA-F0-9]{64}"))) {
                    throw ConnectionException.InvalidServerResponse
                }
                add(IncomingFileOffer(identity, filename, size, hash.lowercase(), item.optString("sender", "Unknown sender"),
                    item.optString("status", "unknown"), item.optDouble("created_at", 0.0), item.optDouble("expires_at", 0.0)))
            }
        }
    }

    fun rejectIncomingOffer(address: String, caDer: ByteArray, token: String, id: String) {
        request(address, "/api/incoming-offers/${encodePathSegment(id)}/reject", caDer, token, "POST", "{}".toByteArray())
    }

    /** Accepts once, reads the server's path-scoped one-use cookie, and immediately consumes it. */
    fun downloadIncomingOffer(
        address: String,
        caDer: ByteArray,
        token: String,
        offer: IncomingFileOffer,
        output: OutputStream,
        checkActive: () -> Unit = {},
        onBytesWritten: (Long) -> Unit = {},
    ): VerifiedDownload {
        checkActive()
        val encodedId = encodePathSegment(offer.id)
        val downloadPath = "/api/incoming-offers/$encodedId/download"
        val cookieName = "__Secure-dd_download_${offer.id}"
        val (acceptedBody, setCookie) = requestWithSetCookie(address,
            "/api/incoming-offers/$encodedId/accept", caDer, token, "POST", "{}".toByteArray())
        val accepted = JSONObject(acceptedBody.toString(Charsets.UTF_8))
        if (accepted.optString("id") != offer.id || accepted.optLong("size", -1L) != offer.size ||
            !accepted.optString("sha256").equals(offer.sha256, ignoreCase = true)) {
            throw ConnectionException.InvalidServerResponse
        }
        val cookie = scopedDownloadCookie(setCookie, cookieName, downloadPath)
            ?: throw ConnectionException.InvalidServerResponse
        checkActive()
        val base = ServerAddress.normalize(address) ?: throw ConnectionException.InvalidAddress
        var connection: HttpsURLConnection? = null
        try {
            connection = URL("$base$downloadPath").openConnection(Proxy.NO_PROXY) as? HttpsURLConnection
                ?: throw ConnectionException.InvalidAddress
            activeDownloadConnection = connection
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 10_000
            connection.readTimeout = 60_000
            connection.useCaches = false
            connection.requestMethod = "GET"
            connection.sslSocketFactory = ServerTrust.sslContext(caDer).socketFactory
            connection.hostnameVerifier = HttpsURLConnection.getDefaultHostnameVerifier()
            connection.setRequestProperty("Accept", "application/octet-stream")
            connection.setRequestProperty("Accept-Encoding", "identity")
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("Cookie", cookie)
            val status = connection.responseCode
            if (status !in 200..299) {
                connection.errorStream?.close()
                throw incomingHttpFailure(status)
            }
            if (status != 200 || connection.contentLengthLong != offer.size) {
                connection.inputStream.close()
                throw DownloadStreamFailure("integrity", "The server returned an unexpected file length.")
            }
            return connection.inputStream.use { input ->
                copyVerifiedDownload(input, output, offer.size, offer.sha256, checkActive = checkActive,
                    onBytesWritten = onBytesWritten)
            }
        } catch (error: ConnectionException) {
            throw error
        } catch (error: DownloadStreamFailure) {
            throw error
        } catch (error: SSLException) {
            throw mapNetworkError(error)
        } catch (error: SocketTimeoutException) {
            throw mapNetworkError(error)
        } catch (error: IOException) {
            throw mapNetworkError(error)
        } finally {
            activeDownloadConnection = null
            connection?.disconnect()
        }
    }

    private fun requestWithSetCookie(address: String, path: String, caDer: ByteArray, token: String,
                                     method: String, body: ByteArray): Pair<ByteArray, String?> {
        val base = ServerAddress.normalize(address) ?: throw ConnectionException.InvalidAddress
        var connection: HttpsURLConnection? = null
        try {
            connection = URL(base + path).openConnection(Proxy.NO_PROXY) as? HttpsURLConnection
                ?: throw ConnectionException.InvalidAddress
            activeConnection = connection
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 5_000
            connection.readTimeout = 5_000
            connection.useCaches = false
            connection.requestMethod = method
            connection.sslSocketFactory = ServerTrust.sslContext(caDer).socketFactory
            connection.hostnameVerifier = HttpsURLConnection.getDefaultHostnameVerifier()
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            connection.doOutput = true
            connection.setFixedLengthStreamingMode(body.size)
            connection.outputStream.use { it.write(body) }
            val status = connection.responseCode
            if (status !in 200..299) {
                connection.errorStream?.close()
                throw incomingHttpFailure(status)
            }
            val response = connection.inputStream.use { input ->
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
            return response to connection.getHeaderField("Set-Cookie")
        } catch (error: ConnectionException) {
            throw error
        } catch (error: IncomingOfferFailure) {
            throw error
        } catch (error: SSLException) {
            throw mapNetworkError(error)
        } catch (error: SocketTimeoutException) {
            throw mapNetworkError(error)
        } catch (error: IOException) {
            throw mapNetworkError(error)
        } finally {
            activeConnection = null
            connection?.disconnect()
        }
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
            activeConnection = connection
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
        } catch (error: IncomingOfferFailure) {
            throw error
        } catch (error: SSLException) {
            throw mapNetworkError(error)
        } catch (error: SocketTimeoutException) {
            throw mapNetworkError(error)
        } catch (error: IOException) {
            throw mapNetworkError(error)
        } finally {
            activeConnection = null
            connection?.disconnect()
        }
    }

    private companion object { const val MAX_RESPONSE_BYTES = 64 * 1024 }
}

data class UploadSource(val name: String, val size: Long, val mimeType: String?, val sha256: String, val open: () -> InputStream)
class TransferFailure(val kind: String, message: String) : Exception(message)
data class StreamDigest(val size: Long, val sha256: String)
fun digestStream(input: InputStream, bufferSize: Int = 64 * 1024, checkActive: () -> Unit = {}): StreamDigest {
    val digest = MessageDigest.getInstance("SHA-256")
    val buffer = ByteArray(bufferSize)
    var size = 0L
    while (true) {
        checkActive()
        val count = input.read(buffer)
        if (count < 0) break
        digest.update(buffer, 0, count); size += count
    }
    return StreamDigest(size, digest.digest().joinToString("") { "%02x".format(it) })
}
private class CountingOutputStream(out: OutputStream, val count: (Long) -> Unit) : java.io.FilterOutputStream(out) {
    var countPayload = false
    override fun write(b: Int) { out.write(b); if (countPayload) count(1) }
    override fun write(b: ByteArray, off: Int, len: Int) { out.write(b, off, len); if (countPayload && len > 0) count(len.toLong()) }
}

class IncomingOfferFailure(val kind: String, message: String) : Exception(message)

internal fun incomingHttpFailure(status: Int): Exception = when (status) {
    401 -> ConnectionException.SessionExpired
    404, 409, 410 -> IncomingOfferFailure("unavailable", "This offer expired or has already been handled. Ask the computer to send it again.")
    507 -> IncomingOfferFailure("storage", "The computer could not access the offered file.")
    else -> ConnectionException.HttpFailure(status)
}

internal fun encodePathSegment(value: String): String = URLEncoder.encode(value, "UTF-8")
    .replace("+", "%20").replace("%21", "!").replace("%27", "'").replace("%28", "(").replace("%29", ")").replace("%7E", "~")

internal fun scopedDownloadCookie(header: String?, name: String, path: String): String? {
    if (header.isNullOrBlank()) return null
    val fields = header.split(';').map(String::trim)
    val pair = fields.firstOrNull()?.takeIf { it.startsWith("$name=") } ?: return null
    val value = pair.substringAfter('=', "")
    val attributes = fields.drop(1)
    if (value.isBlank() || attributes.none { it.equals("Secure", true) } ||
        attributes.none { it.equals("HttpOnly", true) } ||
        attributes.none { it.equals("Path=$path", true) }) return null
    return pair
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
