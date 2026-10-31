package com.devdrop.android.data.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ServerAddressTest {
    @Test fun acceptsExistingHttpsQrAddressAndNormalizesOrigin() {
        assertEquals("https://192.168.1.50:8765", ServerAddress.normalize("https://192.168.1.50:8765/"))
        assertEquals("https://devdrop.local:443", ServerAddress.normalize("https://DevDrop.local"))
    }

    @Test fun refusesHttpCredentialsPathsAndQueryStrings() {
        assertNull(ServerAddress.normalize("http://192.168.1.50:8765"))
        assertNull(ServerAddress.normalize("https://user@server.local:8765"))
        assertNull(ServerAddress.normalize("https://server.local:8765/api"))
        assertNull(ServerAddress.normalize("https://server.local:8765/?token=x"))
        assertNull(ServerAddress.normalize("https://server.local:0"))
    }
}
