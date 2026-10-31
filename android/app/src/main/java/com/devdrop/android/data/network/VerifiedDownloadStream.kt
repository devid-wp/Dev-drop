package com.devdrop.android.data.network

import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest

data class VerifiedDownload(val bytesWritten: Long, val sha256: String)

class DownloadStreamFailure(val kind: String, message: String, cause: Throwable? = null) : IOException(message, cause)

/** Copies bounded chunks to the caller-owned sink and verifies both length and SHA-256. */
fun copyVerifiedDownload(
    input: InputStream,
    output: OutputStream,
    expectedSize: Long,
    expectedSha256: String,
    bufferSize: Int = 64 * 1024,
    checkActive: () -> Unit = {},
    onBytesWritten: (Long) -> Unit = {},
): VerifiedDownload {
    require(expectedSize >= 0)
    require(bufferSize > 0)
    if (!expectedSha256.matches(Regex("[a-fA-F0-9]{64}"))) {
        throw DownloadStreamFailure("metadata", "The server did not provide a valid file integrity digest.")
    }
    val digest = MessageDigest.getInstance("SHA-256")
    val buffer = ByteArray(bufferSize)
    var total = 0L
    while (true) {
        checkActive()
        val count = try { input.read(buffer) } catch (error: IOException) { throw error }
        if (count < 0) break
        if (count == 0) {
            val one = input.read()
            if (one < 0) break
            if (total >= expectedSize) throw DownloadStreamFailure("integrity", "Downloaded file is longer than the server's offer.")
            try { output.write(one) } catch (error: IOException) {
                throw DownloadStreamFailure("storage", "Could not write the downloaded file.", error)
            }
            digest.update(one.toByte())
            total++
            onBytesWritten(total)
            continue
        }
        if (count.toLong() > expectedSize - total) {
            throw DownloadStreamFailure("integrity", "Downloaded file is longer than the server's offer.")
        }
        try { output.write(buffer, 0, count) } catch (error: IOException) {
            throw DownloadStreamFailure("storage", "Could not write the downloaded file.", error)
        }
        digest.update(buffer, 0, count)
        total += count
        onBytesWritten(total)
    }
    val actualHash = digest.digest().joinToString("") { "%02x".format(it) }
    if (total != expectedSize) throw DownloadStreamFailure("integrity", "Download ended before the complete file arrived.")
    val expected = expectedSha256.lowercase()
    if (!MessageDigest.isEqual(actualHash.toByteArray(Charsets.US_ASCII), expected.toByteArray(Charsets.US_ASCII))) {
        throw DownloadStreamFailure("integrity", "File integrity verification failed.")
    }
    checkActive()
    try { output.flush() } catch (error: IOException) {
        throw DownloadStreamFailure("storage", "Could not finish writing the downloaded file.", error)
    }
    return VerifiedDownload(total, actualHash)
}
