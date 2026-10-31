package com.devdrop.android.data.network

import com.devdrop.android.data.model.ConnectionException
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

    fun cancelActiveRequest() { activeConnection?.disconnect() }

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
