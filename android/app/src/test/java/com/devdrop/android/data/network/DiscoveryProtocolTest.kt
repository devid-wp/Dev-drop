package com.devdrop.android.data.network

import java.net.InetAddress
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DiscoveryProtocolTest {
    @Test fun queryUsesBackendMagicAndNonce() {
        assertEquals(
            "{\"magic\":\"DEVDROP_DISCOVERY_V1\",\"action\":\"discover\",\"nonce\":\"0123456789abcdef0123456789abcdef\"}",
            makeDiscoveryQuery("0123456789abcdef0123456789abcdef").toString(Charsets.US_ASCII),
        )
        assertTrue(newDiscoveryNonce().matches(Regex("[a-f0-9]{32}")))
    }

    @Test fun responseUsesPacketSourceRatherThanClaimedIp() {
        val source = InetAddress.getByAddress(byteArrayOf(10, 0, 0, 7))
        val packet = """{"magic":"DEVDROP_DISCOVERY_V1","action":"response","nonce":"n1","name":"Office PC","ip":"192.0.2.1","port":8765}""".toByteArray()
        val server = parseDiscoveryResponse(packet, "n1", source)
        assertEquals("Office PC", server?.name)
        assertEquals("https://10.0.0.7:8765", server?.address)
    }

    @Test fun rejectsWrongNonceMalformedMessagesAndInvalidPorts() {
        val source = InetAddress.getByAddress(byteArrayOf(10, 0, 0, 7))
        val good = """{"magic":"DEVDROP_DISCOVERY_V1","action":"response","nonce":"n1","name":"PC","port":8765}"""
        assertNull(parseDiscoveryResponse(good.toByteArray(), "wrong", source))
        assertNull(parseDiscoveryResponse(good.replace("8765", "65536").toByteArray(), "n1", source))
        assertNull(parseDiscoveryResponse("not json".toByteArray(), "n1", source))
    }
}
