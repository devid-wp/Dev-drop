package com.devdrop.android.data.network

import com.devdrop.android.data.model.ConnectionException
import java.io.IOException
import javax.net.ssl.SSLHandshakeException
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class NetworkFailureTest {
    @Test fun networkAndTlsErrorsAreClassifiedWithoutLeakingExceptionText() {
        assertSame(ConnectionException.NetworkUnavailable, mapNetworkError(IOException("private-token-must-not-appear")))
        assertSame(ConnectionException.TlsIdentity, mapNetworkError(SSLHandshakeException("internal detail")))
        assertTrue(!ConnectionException.NetworkUnavailable.message.orEmpty().contains("private-token"))
    }

    @Test fun authorizationFailuresKeepPairingAndExpiredSessionDistinct() {
        assertSame(ConnectionException.InvalidPairingCode, mapHttpError(401, authenticated = false, pairingRequest = true))
        assertSame(ConnectionException.SessionExpired, mapHttpError(401, authenticated = true, pairingRequest = false))
        assertTrue(mapHttpError(403, authenticated = false, pairingRequest = false) is ConnectionException.HttpFailure)
    }
}
