package com.devdrop.android.data.network

import com.devdrop.android.data.TransferPhase
import com.devdrop.android.data.TransferUiState
import com.devdrop.android.data.transferFailureMessage
import com.devdrop.android.data.model.ConnectionException
import java.io.ByteArrayInputStream
import org.junit.Assert.*
import org.junit.Test

class UploadStreamingTest {
    @Test fun digestReadsStreamAndProducesExactSizeAndSha256() {
        val bytes = "streamed content".toByteArray()
        val result = digestStream(ByteArrayInputStream(bytes), bufferSize = 3)
        assertEquals(bytes.size.toLong(), result.size)
        assertEquals("d9f93d83f082633feac23f4e3d5dea332ca698ba7b00dd6ef8a9e93bae65aa6b", result.sha256)
    }

    @Test fun transferStatesRepresentWaitingSendingAndConfirmedCompletion() {
        assertEquals(TransferPhase.WaitingApproval, TransferUiState(TransferPhase.WaitingApproval).phase)
        val sending = TransferUiState(TransferPhase.Sending, bytesSent = 40, totalBytes = 100, percent = 40)
        assertEquals(40, sending.percent)
        assertEquals(TransferPhase.Completed, TransferUiState(TransferPhase.Completed).phase)
        assertNotEquals(TransferPhase.Completed, sending.phase)
        assertEquals(TransferPhase.Cancelled, TransferUiState(TransferPhase.Cancelled).phase)
        assertEquals(TransferPhase.Error, TransferUiState(TransferPhase.Error).phase)
    }

    @Test fun refusalExpirySessionAndStorageFailuresAreHumanReadable() {
        assertTrue(transferFailureMessage(TransferFailure("rejected", "Owner declined.")).contains("declined"))
        assertTrue(transferFailureMessage(TransferFailure("expired", "Approval expired.")).contains("expired"))
        assertTrue(transferFailureMessage(ConnectionException.SessionExpired).contains("Session expired"))
        assertTrue(transferFailureMessage(ConnectionException.HttpFailure(500)).contains("disk space"))
    }

    @Test fun digestCancellationCheckStopsTheStreamAndResourcesCanBeClosed() {
        var checks = 0
        var closed = false
        val input = object : ByteArrayInputStream(ByteArray(10_000)) {
            override fun close() { closed = true; super.close() }
        }
        try {
            input.use { digestStream(it, bufferSize = 64) { if (++checks == 3) throw java.util.concurrent.CancellationException() } }
            fail("expected cancellation")
        } catch (_: java.util.concurrent.CancellationException) { }
        assertTrue(checks >= 3)
        assertTrue(closed)
    }
}
