package com.devdrop.android.data.model

import org.junit.Assert.assertEquals
import org.junit.Test

class ConnectionStateTest {
    @Test fun phasesFollowRealSearchPairAndDisconnectEvents() {
        assertEquals(ConnectionPhase.Scanning, reduceConnectionPhase(ConnectionPhase.Disconnected, ConnectionEvent.Search))
        assertEquals(ConnectionPhase.NoDevices, reduceConnectionPhase(ConnectionPhase.Scanning, ConnectionEvent.NoneFound))
        assertEquals(ConnectionPhase.ServersFound, reduceConnectionPhase(ConnectionPhase.Scanning, ConnectionEvent.Found))
        assertEquals(ConnectionPhase.PairingRequired, reduceConnectionPhase(ConnectionPhase.ServersFound, ConnectionEvent.SelectServer))
        assertEquals(ConnectionPhase.Connecting, reduceConnectionPhase(ConnectionPhase.PairingRequired, ConnectionEvent.Connect))
        assertEquals(ConnectionPhase.Connected, reduceConnectionPhase(ConnectionPhase.Connecting, ConnectionEvent.Connected))
        assertEquals(ConnectionPhase.Disconnected, reduceConnectionPhase(ConnectionPhase.Connected, ConnectionEvent.Disconnected))
    }

    @Test fun emptySearchAndFailuresAreNotReportedAsConnected() {
        assertEquals(ConnectionPhase.NoDevices, reduceConnectionPhase(ConnectionPhase.Scanning, ConnectionEvent.NoneFound))
        assertEquals(ConnectionPhase.Unavailable, reduceConnectionPhase(ConnectionPhase.Connected, ConnectionEvent.Unavailable))
        assertEquals(ConnectionPhase.Error, reduceConnectionPhase(ConnectionPhase.Connecting, ConnectionEvent.Failed))
    }
}
