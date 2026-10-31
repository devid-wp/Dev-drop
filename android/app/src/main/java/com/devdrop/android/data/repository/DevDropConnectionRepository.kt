package com.devdrop.android.data.repository

import android.content.Context
import com.devdrop.android.data.model.ConnectionException
import com.devdrop.android.data.model.DiscoveredServer
import com.devdrop.android.data.model.TrustedConnection
import com.devdrop.android.data.network.DevDropDiscoveryClient
import com.devdrop.android.data.network.DevDropHttpClient
import com.devdrop.android.data.network.ServerAddress
import com.devdrop.android.data.security.SecureConnectionStore
import com.devdrop.android.data.security.ServerTrust
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

interface DevDropConnectionRepository {
    suspend fun discover(): List<DiscoveredServer>
    suspend fun pair(address: String, caDer: ByteArray, confirmedCaFingerprint: String, code: String): TrustedConnection
    suspend fun reconnect(saved: TrustedConnection): TrustedConnection
    suspend fun verify(connection: TrustedConnection)
    fun savedConnection(): TrustedConnection?
    fun disconnect()
}

class DefaultDevDropConnectionRepository(context: Context) : DevDropConnectionRepository {
    private val discovery = DevDropDiscoveryClient(context)
    private val secureStore = SecureConnectionStore(context)
    private val http = DevDropHttpClient()

    override suspend fun discover(): List<DiscoveredServer> = discovery.scan()

    override suspend fun pair(
        address: String,
        caDer: ByteArray,
        confirmedCaFingerprint: String,
        code: String,
    ): TrustedConnection = withContext(Dispatchers.IO) {
        val normalizedAddress = ServerAddress.normalize(address) ?: throw ConnectionException.InvalidAddress
        val ca = ServerTrust.readCaCertificate(caDer)
        ServerTrust.requireMatchingFingerprint(ca, confirmedCaFingerprint)
        if (!code.matches(Regex("[0-9]{9}"))) throw ConnectionException.InvalidPairingCode

        http.health(normalizedAddress, ca.der)
        val token = http.pair(normalizedAddress, ca.der, code)
        TrustedConnection(normalizedAddress, ca.der, ca.sha256, token).also(secureStore::save)
    }

    override suspend fun reconnect(saved: TrustedConnection): TrustedConnection = withContext(Dispatchers.IO) {
        val address = ServerAddress.normalize(saved.address) ?: throw ConnectionException.InvalidAddress
        val actualCaFingerprint = ServerTrust.readCaCertificate(saved.caCertificateDer).sha256
        if (actualCaFingerprint != saved.caSha256) throw ConnectionException.FingerprintMismatch
        if (saved.token.isBlank()) throw ConnectionException.SessionExpired
        try {
            http.health(address, saved.caCertificateDer)
            http.verifySession(address, saved.caCertificateDer, saved.token)
        } catch (error: ConnectionException.SessionExpired) {
            secureStore.disconnectSession()
            throw error
        }
        saved.copy(address = address)
    }

    override suspend fun verify(connection: TrustedConnection) = withContext(Dispatchers.IO) {
        http.health(connection.address, connection.caCertificateDer)
        try {
            http.verifySession(connection.address, connection.caCertificateDer, connection.token)
        } catch (error: ConnectionException.SessionExpired) {
            secureStore.clearSession()
            throw error
        }
    }

    override fun savedConnection(): TrustedConnection? = secureStore.load()

    override fun disconnect() = secureStore.clear()

    private fun SecureConnectionStore.disconnectSession() = clearSession()
}
