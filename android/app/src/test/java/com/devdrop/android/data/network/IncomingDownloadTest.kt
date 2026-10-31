package com.devdrop.android.data.network

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.OutputStream
import java.security.MessageDigest
import com.devdrop.android.data.IncomingDownloadUiState
import com.devdrop.android.data.IncomingPhase
import com.devdrop.android.data.model.IncomingFileOffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class IncomingDownloadTest {
    @Test fun receiveStatesKeepProgressTruthfulAndCompleteOnlyAfterFullFile() {
        val offer = IncomingFileOffer("offer_123", "archive.zip", 100, "a".repeat(64), "Computer owner", "pending", 1.0, 200.0)
        val choosing = IncomingDownloadUiState(offer, IncomingPhase.ChoosingDestination, "Choose a location")
        val downloading = IncomingDownloadUiState(offer, IncomingPhase.Downloading, "Downloading", 52, 100, 52, 26, 1)
        val completed = IncomingDownloadUiState(offer, IncomingPhase.Completed, "Saved", 100, 100, 100)
        val cancelled = IncomingDownloadUiState(offer, IncomingPhase.Cancelled, "Cancelled")
        val failed = IncomingDownloadUiState(offer, IncomingPhase.Error, "Storage failed")
        assertEquals(IncomingPhase.ChoosingDestination, choosing.phase)
        assertEquals(52L, downloading.bytesReceived)
        assertEquals(52, downloading.percent)
        assertNotEquals(IncomingPhase.Completed, downloading.phase)
        assertEquals(100, completed.percent)
        assertEquals(IncomingPhase.Cancelled, cancelled.phase)
        assertEquals(IncomingPhase.Error, failed.phase)
    }

    @Test fun streamedCopyWritesOnlyBoundedChunksAndVerifiesSizeAndSha256() {
        val bytes = ByteArray(900_000) { (it % 251).toByte() }
        val expected = sha256(bytes)
        var largestRead = 0
        val input = object : ByteArrayInputStream(bytes) {
            override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                largestRead = maxOf(largestRead, length)
                return super.read(buffer, offset, length)
            }
        }
        val output = ByteArrayOutputStream()
        val reports = mutableListOf<Long>()
        val result = copyVerifiedDownload(input, output, bytes.size.toLong(), expected, bufferSize = 32 * 1024,
            onBytesWritten = reports::add)
        assertEquals(bytes.size.toLong(), result.bytesWritten)
        assertEquals(expected, result.sha256)
        assertTrue(bytes.contentEquals(output.toByteArray()))
        assertTrue(largestRead <= 32 * 1024)
        assertTrue(reports.zipWithNext().all { (a, b) -> b > a })
        assertEquals(bytes.size.toLong(), reports.last())
    }

    @Test fun incompleteOversizedAndMismatchedFilesAreRejected() {
        val bytes = "trusted file".toByteArray()
        val hash = sha256(bytes)
        assertEquals("integrity", assertThrows(DownloadStreamFailure::class.java) {
            copyVerifiedDownload(ByteArrayInputStream(bytes.copyOf(bytes.size - 1)), ByteArrayOutputStream(), bytes.size.toLong(), hash)
        }.kind)
        assertEquals("integrity", assertThrows(DownloadStreamFailure::class.java) {
            copyVerifiedDownload(ByteArrayInputStream(bytes + byteArrayOf(1)), ByteArrayOutputStream(), bytes.size.toLong(), hash)
        }.kind)
        assertEquals("integrity", assertThrows(DownloadStreamFailure::class.java) {
            copyVerifiedDownload(ByteArrayInputStream(bytes), ByteArrayOutputStream(), bytes.size.toLong(), "0".repeat(64))
        }.kind)
    }

    @Test fun cancellationAndSinkErrorsAreDistinctAndClosable() {
        var closedInput = false
        var closedOutput = false
        var checks = 0
        val input = object : ByteArrayInputStream(ByteArray(100_000)) {
            override fun close() { closedInput = true; super.close() }
        }
        val output = object : ByteArrayOutputStream() {
            override fun close() { closedOutput = true; super.close() }
        }
        assertThrows(java.util.concurrent.CancellationException::class.java) {
            input.use { source -> output.use { sink ->
                copyVerifiedDownload(source, sink, 100_000, "0".repeat(64), bufferSize = 1024,
                    checkActive = { if (++checks == 3) throw java.util.concurrent.CancellationException() })
            } }
        }
        assertTrue(closedInput)
        assertTrue(closedOutput)

        val failingSink = object : OutputStream() {
            override fun write(value: Int) { throw IOException("disk full") }
            override fun write(buffer: ByteArray, offset: Int, length: Int) { throw IOException("disk full") }
        }
        assertEquals("storage", assertThrows(DownloadStreamFailure::class.java) {
            copyVerifiedDownload(ByteArrayInputStream(byteArrayOf(1)), failingSink, 1, sha256(byteArrayOf(1)))
        }.kind)
    }

    @Test fun onlyTheOfferScopedSecureOneUseCookieIsAccepted() {
        val path = "/api/incoming-offers/abc_123/download"
        val name = "__Secure-dd_download_abc_123"
        val valid = "$name=grant; HttpOnly; Max-Age=300; Path=$path; SameSite=strict; Secure"
        assertEquals("$name=grant", scopedDownloadCookie(valid, name, path))
        assertEquals(null, scopedDownloadCookie(valid.replace("; Secure", ""), name, path))
        assertEquals(null, scopedDownloadCookie(valid.replace("$path", "/api/incoming-offers/other/download"), name, path))
        assertEquals(null, scopedDownloadCookie(valid.replace("$name=grant", "other=grant"), name, path))
    }

    @Test fun expiredSessionAndSpentOfferHaveSpecificFailures() {
        assertTrue(incomingHttpFailure(401) is com.devdrop.android.data.model.ConnectionException.SessionExpired)
        assertEquals("unavailable", (incomingHttpFailure(409) as IncomingOfferFailure).kind)
        assertEquals("unavailable", (incomingHttpFailure(404) as IncomingOfferFailure).kind)
        assertFalse(incomingHttpFailure(503) is IncomingOfferFailure)
    }

    private fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it) }
}
