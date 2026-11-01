package com.devdrop.android.data.repository

import android.content.Context
import android.net.Uri
import com.devdrop.android.data.model.ConnectionException
import com.devdrop.android.data.model.DiscoveredServer
import com.devdrop.android.data.model.IncomingFileOffer
import com.devdrop.android.data.model.TrustedConnection
import com.devdrop.android.data.network.DevDropDiscoveryClient
import com.devdrop.android.data.network.DevDropHttpClient
import com.devdrop.android.data.network.DownloadStreamFailure
import com.devdrop.android.data.network.IncomingOfferFailure
import com.devdrop.android.data.network.ServerAddress
import com.devdrop.android.data.network.VerifiedDownload
import com.devdrop.android.data.security.SecureConnectionStore
import com.devdrop.android.data.security.ServerTrust
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlin.coroutines.coroutineContext
import java.io.IOException

interface DevDropConnectionRepository {
    suspend fun discover(): List<DiscoveredServer>
    suspend fun pair(address: String, caDer: ByteArray, confirmedCaFingerprint: String, code: String): TrustedConnection
    suspend fun pairQr(address: String, caDer: ByteArray, caFingerprint: String, serverFingerprint: String,
                       windowId: String, qrToken: String, code: String, device: String): TrustedConnection
    fun cancelPairing()
    suspend fun reconnect(saved: TrustedConnection): TrustedConnection
    suspend fun verify(connection: TrustedConnection)
    suspend fun incomingOffers(connection: TrustedConnection): List<IncomingFileOffer>
    suspend fun rejectIncomingOffer(connection: TrustedConnection, offerId: String)
    suspend fun downloadIncomingOffer(connection: TrustedConnection, offer: IncomingFileOffer, destination: Uri,
                                      checkActive: () -> Unit, onBytesWritten: (Long) -> Unit): VerifiedDownload
    suspend fun confirmIncomingReceipt(connection: TrustedConnection, offer: IncomingFileOffer, result: VerifiedDownload)
    fun discardIncomingDestination(destination: Uri)
    fun cancelIncomingDownload()
    fun invalidateSession()
    fun savedConnection(): TrustedConnection?
    suspend fun disconnect()
}

class DefaultDevDropConnectionRepository(context: Context) : DevDropConnectionRepository {
    private val discovery = DevDropDiscoveryClient(context)
    private val secureStore = SecureConnectionStore(context)
    private val http = DevDropHttpClient()
    private val qrPairingApi = DevDropHttpClient()
    private val incomingApi = DevDropHttpClient()
    private val incomingDownloader = DevDropHttpClient()
    private val receiptApi = DevDropHttpClient()
    private val contentResolver = context.applicationContext.contentResolver

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

    override suspend fun pairQr(address: String, caDer: ByteArray, caFingerprint: String, serverFingerprint: String,
                                windowId: String, qrToken: String, code: String, device: String): TrustedConnection {
        val normalizedAddress = ServerAddress.normalize(address) ?: throw ConnectionException.InvalidAddress
        val ca = ServerTrust.readCaCertificate(caDer)
        if (ca.sha256 != caFingerprint || !code.matches(Regex("[0-9]{6}"))) {
            throw ConnectionException.FingerprintMismatch
        }
        withContext(Dispatchers.IO) { qrPairingApi.health(normalizedAddress, ca.der, serverFingerprint) }
        val pollKey = java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(
            ByteArray(32).also(java.security.SecureRandom()::nextBytes))
        val claimId = withContext(Dispatchers.IO) {
            qrPairingApi.claimQrPairing(normalizedAddress, ca.der, serverFingerprint,
                windowId, qrToken, pollKey, code, device)
        }
        val deadline = System.currentTimeMillis() + 120_000
        while (System.currentTimeMillis() < deadline) {
            coroutineContext.ensureActive()
            val (state, token) = withContext(Dispatchers.IO) {
                qrPairingApi.qrPairingResult(normalizedAddress, ca.der, serverFingerprint, claimId, pollKey)
            }
            if (state == "approved" && !token.isNullOrBlank() && token.length in 16..256) {
                val trusted = TrustedConnection(normalizedAddress, ca.der, ca.sha256, token)
                secureStore.save(trusted)
                return trusted
            }
            if (state !in setOf("pending", "approved")) throw ConnectionException.PairingExpired
            delay(500)
        }
        throw ConnectionException.PairingExpired
    }

    override fun cancelPairing() {
        qrPairingApi.cancelActiveRequest()
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

    override suspend fun incomingOffers(connection: TrustedConnection): List<IncomingFileOffer> = withContext(Dispatchers.IO) {
        incomingApi.incomingOffers(connection.address, connection.caCertificateDer, connection.token)
    }

    override suspend fun rejectIncomingOffer(connection: TrustedConnection, offerId: String) = withContext(Dispatchers.IO) {
        try {
            incomingApi.rejectIncomingOffer(connection.address, connection.caCertificateDer, connection.token, offerId)
        } catch (error: ConnectionException.HttpFailure) {
            if (error.status == 404 || error.status == 409) throw IncomingOfferFailure("unavailable", "This offer expired or was already handled.")
            throw error
        }
    }

    override suspend fun downloadIncomingOffer(connection: TrustedConnection, offer: IncomingFileOffer, destination: Uri,
                                               checkActive: () -> Unit, onBytesWritten: (Long) -> Unit): VerifiedDownload = withContext(Dispatchers.IO) {
        var saved = false
        try {
            val output = try {
                contentResolver.openOutputStream(destination, "wt")
                    ?: throw IncomingOfferFailure("storage", "Android could not open the selected save location.")
            } catch (error: IncomingOfferFailure) { throw error
            } catch (error: SecurityException) {
                throw IncomingOfferFailure("storage", "Android no longer has access to the selected save location.")
            } catch (error: IOException) {
                throw IncomingOfferFailure("storage", "Android could not open the selected save location.")
            }
            val result = output.use {
                incomingDownloader.downloadIncomingOffer(connection.address, connection.caCertificateDer,
                    connection.token, offer, it, checkActive, onBytesWritten)
            }
            saved = true
            result
        } catch (error: CancellationException) {
            throw error
        } catch (error: ConnectionException) {
            throw error
        } catch (error: IncomingOfferFailure) {
            throw error
        } catch (error: DownloadStreamFailure) {
            throw error
        } catch (error: IOException) {
            throw IncomingOfferFailure("storage", "Could not finish writing the file. Check the selected storage location.")
        } catch (error: SecurityException) {
            throw IncomingOfferFailure("storage", "Android denied access to the selected save location.")
        } finally {
            if (!saved) deletePartial(destination)
        }
    }

    override suspend fun confirmIncomingReceipt(connection: TrustedConnection, offer: IncomingFileOffer,
                                                result: VerifiedDownload) = withContext(Dispatchers.IO) {
        receiptApi.confirmIncomingReceipt(connection.address, connection.caCertificateDer,
            connection.token, offer, result)
    }

    override fun cancelIncomingDownload() {
        incomingDownloader.cancelActiveDownload()
        incomingDownloader.cancelActiveRequest()
        receiptApi.cancelActiveRequest()
    }

    override fun discardIncomingDestination(destination: Uri) = deletePartial(destination)

    override fun invalidateSession() = secureStore.clearSession()

    private fun deletePartial(uri: Uri) {
        val deleted = runCatching { android.provider.DocumentsContract.deleteDocument(contentResolver, uri) }.getOrDefault(false)
        if (!deleted) runCatching { contentResolver.delete(uri, null, null) }
    }

    override fun savedConnection(): TrustedConnection? = secureStore.load()

    override suspend fun disconnect() = withContext(Dispatchers.IO) {
        val saved = secureStore.load()
        secureStore.clear()
        if (saved != null) runCatching {
            http.revokeSession(saved.address, saved.caCertificateDer, saved.token)
        }
        Unit
    }

    private fun SecureConnectionStore.disconnectSession() = clearSession()
}
