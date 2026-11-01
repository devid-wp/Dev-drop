package com.devdrop.android.data

import android.app.Application
import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.devdrop.android.data.model.ConnectionEvent
import com.devdrop.android.data.model.ConnectionException
import com.devdrop.android.data.model.ConnectionPhase
import com.devdrop.android.data.model.ConnectionUiState
import com.devdrop.android.data.model.DiscoveredServer
import com.devdrop.android.data.model.IncomingFileOffer
import com.devdrop.android.data.model.reduceConnectionPhase
import com.devdrop.android.data.network.ServerAddress
import com.devdrop.android.data.network.DevDropHttpClient
import com.devdrop.android.data.network.UploadSource
import com.devdrop.android.data.network.TransferFailure
import com.devdrop.android.data.network.IncomingOfferFailure
import com.devdrop.android.data.network.DownloadStreamFailure
import com.devdrop.android.data.network.VerifiedDownload
import com.devdrop.android.data.repository.DefaultDevDropConnectionRepository
import com.devdrop.android.data.repository.DevDropConnectionRepository
import com.devdrop.android.data.security.ServerTrust
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.ensureActive
import kotlin.math.roundToInt
import kotlinx.coroutines.withContext

data class DevDropUiState(
    val selectedFiles: List<PickedFile> = emptyList(),
    val notice: String? = null,
    val connection: ConnectionUiState = ConnectionUiState(),
    val transfer: TransferUiState = TransferUiState(),
    val incomingOffers: List<IncomingFileOffer> = emptyList(),
    val incomingOffersError: String? = null,
    val incomingDownload: IncomingDownloadUiState? = null,
)

enum class TransferPhase { Idle, Preparing, WaitingApproval, Sending, Completed, Error, Cancelled }
data class TransferUiState(val phase: TransferPhase = TransferPhase.Idle, val message: String? = null,
    val bytesSent: Long = 0, val totalBytes: Long = 0, val percent: Int = 0, val bytesPerSecond: Long? = null,
    val etaSeconds: Long? = null)

enum class IncomingPhase { ChoosingDestination, Preparing, Downloading, ConfirmingReceipt, SavedUnconfirmed, Completed, Error, Cancelled }
data class IncomingDownloadUiState(
    val offer: IncomingFileOffer,
    val phase: IncomingPhase,
    val message: String,
    val bytesReceived: Long = 0,
    val totalBytes: Long = offer.size,
    val percent: Int = 0,
    val bytesPerSecond: Long? = null,
    val etaSeconds: Long? = null,
)

internal fun transferFailureMessage(error: Throwable): String = when (error) {
    is TransferFailure -> error.message.orEmpty()
    is ConnectionException.SessionExpired -> "Session expired. Connect to the computer again."
    is ConnectionException.NetworkUnavailable -> "Network connection failed. Check the Wi-Fi and server."
    is ConnectionException.HttpFailure -> if (error.status == 507 || error.status == 500) "The computer could not save the files. Check available disk space and permissions." else error.message.orEmpty()
    else -> error.message?.takeIf { it.contains("Could not") || it.contains("open") } ?: "Could not send files. Check connection and available disk space."
}

internal fun incomingFailureMessage(error: Throwable): String = when (error) {
    is IncomingOfferFailure -> error.message.orEmpty()
    is DownloadStreamFailure -> error.message.orEmpty()
    is ConnectionException.SessionExpired -> "Session expired. Connect to the computer again."
    is ConnectionException.TlsIdentity -> "The server certificate could not be verified. Check the saved CA and server address."
    is ConnectionException.NetworkUnavailable -> "Connection lost during download. This one-use offer cannot be resumed; ask the computer to send it again."
    is ConnectionException.HttpFailure -> when (error.status) {
        401 -> "Session expired. Connect to the computer again."
        404, 409, 410 -> "This offer expired or was already handled. Ask the computer to send it again."
        else -> "The server could not provide this file (HTTP ${error.status})."
    }
    else -> "Could not save the incoming file. Check the selected storage location and try again."
}

class DevDropViewModel(
    application: Application,
    private val repository: DevDropConnectionRepository = DefaultDevDropConnectionRepository(application),
) : AndroidViewModel(application) {
    private val transferHttp = DevDropHttpClient()
    private var transferJob: Job? = null
    private var incomingDownloadJob: Job? = null
    private var destinationOffer: IncomingFileOffer? = null
    private data class PendingReceipt(val connection: com.devdrop.android.data.model.TrustedConnection,
                                      val offer: IncomingFileOffer, val result: VerifiedDownload)
    private var pendingReceipt: PendingReceipt? = null
    private val _uiState = MutableStateFlow(DevDropUiState())
    val uiState: StateFlow<DevDropUiState> = _uiState.asStateFlow()

    init { restoreConnection() }

    fun searchServers() {
        updateConnection { it.copy(phase = reduceConnectionPhase(it.phase, ConnectionEvent.Search), errorMessage = null, servers = emptyList()) }
        viewModelScope.launch {
            runCatching { repository.discover() }
                .onSuccess { servers ->
                    updateConnection {
                        it.copy(phase = reduceConnectionPhase(it.phase, if (servers.isEmpty()) ConnectionEvent.NoneFound else ConnectionEvent.Found), servers = servers)
                    }
                }
                .onFailure { error -> updateConnection { it.copy(phase = ConnectionPhase.Error, errorMessage = safeMessage(error)) } }
        }
    }

    fun selectDiscoveredServer(server: DiscoveredServer) {
        updateConnection {
            it.copy(phase = ConnectionPhase.PairingRequired, addressDraft = server.address, errorMessage = null,
                selectedCaDer = null, selectedCaSha256 = null, selectedCaAddress = null,
                fingerprintConfirmation = "", pairingCode = "")
        }
    }

    fun setAddressDraft(value: String) = updateConnection { current ->
        val bounded = value.take(260)
        val normalized = ServerAddress.normalize(bounded)
        val keepTrust = current.selectedCaAddress != null && current.selectedCaAddress == normalized
        current.copy(addressDraft = bounded, errorMessage = null,
            selectedCaDer = if (keepTrust) current.selectedCaDer else null,
            selectedCaSha256 = if (keepTrust) current.selectedCaSha256 else null,
            selectedCaAddress = if (keepTrust) current.selectedCaAddress else null,
            fingerprintConfirmation = if (keepTrust) current.fingerprintConfirmation else "")
    }

    fun continueToConnectionSetup(): Boolean {
        val address = ServerAddress.normalize(_uiState.value.connection.addressDraft) ?: run {
            updateConnection { it.copy(errorMessage = "Enter a valid HTTPS server address.") }
            return false
        }
        updateConnection { current ->
            val keepTrust = current.selectedCaAddress == address
            current.copy(addressDraft = address, phase = ConnectionPhase.PairingRequired, errorMessage = null,
                selectedCaDer = if (keepTrust) current.selectedCaDer else null,
                selectedCaSha256 = if (keepTrust) current.selectedCaSha256 else null,
                selectedCaAddress = if (keepTrust) current.selectedCaAddress else null,
                fingerprintConfirmation = if (keepTrust) current.fingerprintConfirmation else "")
        }
        return true
    }

    fun useQrPayload(payload: String): Boolean {
        val address = ServerAddress.normalize(payload) ?: run {
            updateConnection { it.copy(phase = ConnectionPhase.Error, errorMessage = "This QR is not a Dev-Drop HTTPS address.") }
            return false
        }
        updateConnection { current ->
            val keepTrust = current.selectedCaAddress == address
            current.copy(addressDraft = address, phase = ConnectionPhase.PairingRequired, errorMessage = null,
                selectedCaDer = if (keepTrust) current.selectedCaDer else null,
                selectedCaSha256 = if (keepTrust) current.selectedCaSha256 else null,
                selectedCaAddress = if (keepTrust) current.selectedCaAddress else null,
                fingerprintConfirmation = if (keepTrust) current.fingerprintConfirmation else "")
        }
        return true
    }

    fun selectCaCertificate(uri: Uri) {
        viewModelScope.launch {
            val bytes = runCatching { withContext(Dispatchers.IO) { getApplication<Application>().contentResolver.readSmallDocument(uri) } }
                .getOrElse { updateConnection { it.copy(errorMessage = "Could not read this certificate file.") }; return@launch }
            runCatching { ServerTrust.readCaCertificate(bytes) }
                .onSuccess { ca -> updateConnection { current -> current.copy(selectedCaDer = ca.der,
                    selectedCaSha256 = ca.sha256, selectedCaAddress = ServerAddress.normalize(current.addressDraft),
                    fingerprintConfirmation = "", errorMessage = null) } }
                .onFailure { error -> updateConnection { current -> current.copy(selectedCaDer = null,
                    selectedCaSha256 = null, errorMessage = safeMessage(error)) } }
        }
    }

    fun setFingerprintConfirmation(value: String) = updateConnection { it.copy(fingerprintConfirmation = value.filter { c -> c.isDigit() || c.lowercaseChar() in 'a'..'f' || c == ':' || c.isWhitespace() }.take(100)) }
    fun setPairingCode(value: String) = updateConnection { it.copy(pairingCode = value.filter(Char::isDigit).take(9)) }

    fun pair() {
        val current = _uiState.value.connection
        val ca = current.selectedCaDer ?: run { updateConnection { it.copy(errorMessage = "Select the Dev-Drop CA certificate first.") }; return }
        updateConnection { it.copy(phase = reduceConnectionPhase(it.phase, ConnectionEvent.Connect), errorMessage = null) }
        viewModelScope.launch {
            runCatching { repository.pair(current.addressDraft, ca, current.fingerprintConfirmation, current.pairingCode) }
                .onSuccess { saved ->
                    updateConnection {
                        it.copy(phase = reduceConnectionPhase(it.phase, ConnectionEvent.Connected), connectedAddress = saved.address,
                            connectedName = saved.serverName, trustedFingerprint = saved.caSha256, addressDraft = saved.address,
                            errorMessage = null, pairingCode = "")
                    }
                }
                .onFailure { error -> updateConnection { it.copy(phase = ConnectionPhase.Error, errorMessage = safeMessage(error)) } }
        }
    }

    fun retryConnection() {
        val saved = repository.savedConnection()
        if (saved == null || saved.token.isBlank()) {
            updateConnection { it.copy(phase = ConnectionPhase.PairingRequired, errorMessage = null) }
            return
        }
        updateConnection { it.copy(phase = ConnectionPhase.Connecting, errorMessage = null) }
        viewModelScope.launch {
            runCatching { repository.reconnect(saved) }
                .onSuccess { connection -> updateConnection { it.copy(phase = ConnectionPhase.Connected,
                    connectedAddress = connection.address, connectedName = connection.serverName,
                    trustedFingerprint = connection.caSha256, addressDraft = connection.address, errorMessage = null) } }
                .onFailure { error ->
                    val expired = error is ConnectionException.SessionExpired
                    updateConnection { it.copy(phase = if (expired) ConnectionPhase.PairingRequired else ConnectionPhase.Unavailable,
                        connectedAddress = null, connectedName = null, errorMessage = safeMessage(error)) }
                }
        }
    }

    fun checkConnection() {
        val saved = repository.savedConnection() ?: return retryConnection()
        viewModelScope.launch {
            runCatching { repository.verify(saved) }
                .onSuccess { updateConnection { it.copy(phase = ConnectionPhase.Connected, errorMessage = null) } }
                .onFailure { error -> updateConnection { it.copy(
                    phase = if (error is ConnectionException.SessionExpired) ConnectionPhase.PairingRequired else ConnectionPhase.Unavailable,
                    connectedAddress = if (error is ConnectionException.SessionExpired) null else it.connectedAddress,
                    connectedName = if (error is ConnectionException.SessionExpired) null else it.connectedName,
                    errorMessage = safeMessage(error)) } }
        }
    }

    fun disconnect() {
        cancelIncomingDownload()
        transferHttp.cancelActiveRequest()
        transferJob?.cancel()
        viewModelScope.launch(Dispatchers.IO) {
            repository.disconnect()
            _uiState.value = DevDropUiState(connection = ConnectionUiState(phase = ConnectionPhase.Disconnected))
        }
    }

    fun addPickedFiles(uris: List<Uri>) {
        if (uris.isEmpty()) return
        viewModelScope.launch {
            val resolver = getApplication<Application>().contentResolver
            val files = withContext(Dispatchers.IO) { uris.mapNotNull { resolver.describe(it) } }
            _uiState.value = _uiState.value.copy(
                selectedFiles = (_uiState.value.selectedFiles + files).distinctBy(PickedFile::uri),
                notice = if (files.isEmpty()) "Could not read the selected files." else null,
            )
        }
    }

    fun removeFile(file: PickedFile) { _uiState.value = _uiState.value.copy(selectedFiles = _uiState.value.selectedFiles - file) }

    suspend fun refreshIncomingOffersNow() {
        val saved = repository.savedConnection()
        if (saved == null || _uiState.value.connection.phase != ConnectionPhase.Connected) {
            _uiState.value = _uiState.value.copy(incomingOffers = emptyList(),
                incomingOffersError = if (saved == null) "Connect to a Dev-Drop computer to see incoming files." else null)
            return
        }
        try {
            val offers = repository.incomingOffers(saved)
            _uiState.value = _uiState.value.copy(incomingOffers = offers, incomingOffersError = null)
        } catch (error: Throwable) {
            if (error is kotlinx.coroutines.CancellationException) throw error
            if (error is ConnectionException.SessionExpired) {
                repository.invalidateSession()
                updateConnection { it.copy(phase = ConnectionPhase.PairingRequired, connectedAddress = null,
                    connectedName = null, errorMessage = error.message) }
                _uiState.value = _uiState.value.copy(incomingOffers = emptyList(), incomingOffersError = error.message)
            } else {
                _uiState.value = _uiState.value.copy(incomingOffersError = incomingFailureMessage(error))
            }
        }
    }

    fun refreshIncomingOffers() { viewModelScope.launch { refreshIncomingOffersNow() } }

    fun beginIncomingAcceptance(offer: IncomingFileOffer): Boolean {
        if (incomingDownloadJob?.isActive == true || destinationOffer != null) return false
        val current = _uiState.value.incomingOffers.firstOrNull { it.id == offer.id && it.status == "pending" }
        if (current == null) {
            showNotice("This offer is no longer pending. Refresh the list.")
            return false
        }
        destinationOffer = current
        _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(current,
            IncomingPhase.ChoosingDestination, "Choose where to save ${current.filename}. The offer will be accepted after you choose."))
        return true
    }

    fun incomingDestinationResult(uri: Uri?) {
        val offer = destinationOffer
        if (offer == null) {
            uri?.let(repository::discardIncomingDestination)
            return
        }
        destinationOffer = null
        if (uri == null) {
            _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(offer,
                IncomingPhase.Cancelled, "Save location cancelled. The offer is still pending."))
            return
        }
        if (incomingDownloadJob?.isActive == true) return
        incomingDownloadJob = viewModelScope.launch {
            val saved = repository.savedConnection()
            if (saved == null || _uiState.value.connection.phase != ConnectionPhase.Connected) {
                repository.discardIncomingDestination(uri)
                _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(offer,
                    IncomingPhase.Error, "Connect to the computer again before downloading."))
                return@launch
            }
            _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(offer,
                IncomingPhase.Preparing, "Accepting offer and starting secure download…"))
            var sampleStartedAt = 0L
            var sampleBytes = 0L
            try {
                val result = repository.downloadIncomingOffer(saved, offer, uri, { ensureActive() }) { bytes ->
                    val now = System.nanoTime()
                    if (sampleStartedAt == 0L) { sampleStartedAt = now; sampleBytes = bytes }
                    val elapsedNanos = now - sampleStartedAt
                    val deltaBytes = bytes - sampleBytes
                    val rate = (deltaBytes * 1_000_000_000.0 / elapsedNanos.coerceAtLeast(1)).toLong()
                        .takeIf { elapsedNanos >= 1_000_000_000L && it > 0 }
                    if (rate != null) { sampleStartedAt = now; sampleBytes = bytes }
                    val remaining = (offer.size - bytes).coerceAtLeast(0)
                    _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(offer,
                        IncomingPhase.Downloading, "Downloading ${offer.filename}…", bytes, offer.size,
                        if (offer.size > 0) (bytes * 100.0 / offer.size).roundToInt().coerceIn(0, 99) else 0,
                        rate, if (rate != null) remaining / rate else null))
                }
                _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(offer,
                    IncomingPhase.ConfirmingReceipt, "File saved and SHA-256 verified. Confirming receipt with the computer…",
                    result.bytesWritten, offer.size, 100))
                try {
                    repository.confirmIncomingReceipt(saved, offer, result)
                    pendingReceipt = null
                } catch (error: kotlinx.coroutines.CancellationException) {
                    throw error
                } catch (error: Throwable) {
                    pendingReceipt = PendingReceipt(saved, offer, result)
                    if (error is ConnectionException.SessionExpired) {
                        repository.invalidateSession()
                        updateConnection { it.copy(phase = ConnectionPhase.PairingRequired, connectedAddress = null,
                            connectedName = null, errorMessage = error.message) }
                    }
                    _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(offer,
                        IncomingPhase.SavedUnconfirmed,
                        "File saved and SHA-256 verified, but the server receipt was not confirmed. ${incomingFailureMessage(error)} Retry when connected.",
                        result.bytesWritten, offer.size, 100))
                    refreshIncomingOffersNow()
                    return@launch
                }
                _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(offer,
                    IncomingPhase.Completed, "Saved and verified · server confirmed receipt.",
                    result.bytesWritten, offer.size, 100))
                refreshIncomingOffersNow()
            } catch (error: kotlinx.coroutines.CancellationException) {
                repository.cancelIncomingDownload()
                _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(offer,
                    IncomingPhase.Cancelled, "Download cancelled. Any partial file was removed."))
                throw error
            } catch (error: Throwable) {
                if (error is ConnectionException.SessionExpired) {
                    repository.invalidateSession()
                    updateConnection { it.copy(phase = ConnectionPhase.PairingRequired, connectedAddress = null,
                        connectedName = null, errorMessage = error.message) }
                }
                _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(offer,
                    IncomingPhase.Error, incomingFailureMessage(error)))
                refreshIncomingOffersNow()
            }
        }
    }

    fun retryIncomingReceipt() {
        val pending = pendingReceipt ?: return
        if (incomingDownloadJob?.isActive == true) return
        incomingDownloadJob = viewModelScope.launch {
            try {
                repository.confirmIncomingReceipt(pending.connection, pending.offer, pending.result)
                pendingReceipt = null
                _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(pending.offer,
                    IncomingPhase.Completed, "Saved and verified · server confirmed receipt.",
                    pending.result.bytesWritten, pending.offer.size, 100))
                refreshIncomingOffersNow()
            } catch (error: kotlinx.coroutines.CancellationException) {
                throw error
            } catch (error: Throwable) {
                if (error is ConnectionException.SessionExpired) {
                    repository.invalidateSession()
                    updateConnection { it.copy(phase = ConnectionPhase.PairingRequired, connectedAddress = null,
                        connectedName = null, errorMessage = error.message) }
                }
                _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(pending.offer,
                    IncomingPhase.SavedUnconfirmed,
                    "File remains saved and verified, but receipt confirmation failed. ${incomingFailureMessage(error)} Retry when connected.",
                    pending.result.bytesWritten, pending.offer.size, 100))
            }
        }
    }

    fun rejectIncomingOffer(offer: IncomingFileOffer) {
        if (offer.status != "pending" || incomingDownloadJob?.isActive == true || destinationOffer != null) return
        viewModelScope.launch {
            val saved = repository.savedConnection() ?: return@launch
            runCatching { repository.rejectIncomingOffer(saved, offer.id) }
                .onSuccess { showNotice("${offer.filename} declined."); refreshIncomingOffersNow() }
                .onFailure { error ->
                    if (error is ConnectionException.SessionExpired) {
                        repository.invalidateSession()
                        updateConnection { it.copy(phase = ConnectionPhase.PairingRequired, connectedAddress = null,
                            connectedName = null, errorMessage = error.message) }
                    }
                    _uiState.value = _uiState.value.copy(incomingOffersError = incomingFailureMessage(error))
                    refreshIncomingOffersNow()
                }
        }
    }

    fun cancelIncomingDownload() {
        val choosing = destinationOffer
        if (choosing != null) {
            destinationOffer = null
            _uiState.value = _uiState.value.copy(incomingDownload = IncomingDownloadUiState(choosing,
                IncomingPhase.Cancelled, "Save location cancelled. The offer is still pending."))
            return
        }
        repository.cancelIncomingDownload()
        incomingDownloadJob?.cancel()
    }

    fun sendSelectedFiles() {
        if (transferJob?.isActive == true) return
        val selected = _uiState.value.selectedFiles
        val saved = repository.savedConnection()
        if (selected.isEmpty() || saved == null) { showNotice(if (saved == null) "Connect to a Dev-Drop server before sending." else "Choose at least one file."); return }
        transferJob = viewModelScope.launch {
            setTransfer(TransferUiState(TransferPhase.Preparing, "Preparing files…"))
            var requestId: String? = null
            try {
                val resolver = getApplication<Application>().contentResolver
                val sources = withContext(Dispatchers.IO) {
                    selected.map { picked ->
                        val uri = Uri.parse(picked.uri)
                        val measured = resolver.openInputStream(uri)?.use { input ->
                            com.devdrop.android.data.network.digestStream(input) { ensureActive() }
                        } ?: throw java.io.IOException("Could not open ${picked.name}")
                        // Verify the provider can reopen before asking the owner to approve.
                        resolver.openInputStream(uri)?.use { }
                            ?: throw java.io.IOException("This provider cannot reopen ${picked.name}")
                        val uploadName = picked.name.filterNot(Char::isISOControl).take(255).ifBlank { "upload.bin" }
                        UploadSource(uploadName, measured.size, picked.mimeType, measured.sha256) {
                            resolver.openInputStream(uri) ?: throw java.io.IOException("Could not reopen ${picked.name}")
                        }
                    }
                }
                val total = sources.sumOf { it.size }
                var completedBytes = 0L
                var activeUploadNanos = 0L
                sources.forEachIndexed { index, source ->
                    ensureActive()
                    requestId = withContext(Dispatchers.IO) {
                        transferHttp.createFileRequest(saved.address, saved.caCertificateDer, saved.token, listOf(source))
                    }
                    setTransfer(TransferUiState(TransferPhase.WaitingApproval, "Waiting for approval for ${source.name}…", completedBytes, total,
                        if (total > 0) (completedBytes * 100 / total).toInt() else 0))
                    while (true) {
                        ensureActive()
                        val status = withContext(Dispatchers.IO) { transferHttp.transferState(saved.address, saved.caCertificateDer, saved.token, requestId!!) }
                        when (status) {
                            "approved" -> break
                            "rejected" -> throw TransferFailure("rejected", "The computer owner declined ${source.name}.")
                            "expired" -> throw TransferFailure("expired", "Approval expired for ${source.name}. Start a new transfer request.")
                            "cancelled" -> throw TransferFailure("rejected", "The transfer request for ${source.name} was cancelled.")
                        }
                        delay(1000)
                    }
                    val started = System.nanoTime()
                    setTransfer(TransferUiState(TransferPhase.Sending, "Sending ${source.name}…", completedBytes, total,
                        if (total > 0) (completedBytes * 100 / total).toInt() else 0))
                    withContext(Dispatchers.IO) {
                        transferHttp.uploadFiles(saved.address, saved.caCertificateDer, saved.token, requestId!!, listOf(source)) { bytes ->
                            val elapsed = activeUploadNanos + (System.nanoTime() - started).coerceAtLeast(1)
                            val elapsedSeconds = elapsed / 1_000_000_000.0
                            val transferred = completedBytes + bytes
                            val rate = (transferred / elapsedSeconds).toLong().takeIf { elapsedSeconds >= 1.0 && it > 0 }
                            val remaining = (total - transferred).coerceAtLeast(0)
                            _uiState.value = _uiState.value.copy(transfer = TransferUiState(TransferPhase.Sending, "Sending ${source.name}…", transferred, total,
                                if (total > 0) ((transferred * 100.0 / total).roundToInt()).coerceIn(0, 99) else 0,
                                rate, if (rate != null) remaining / rate else null))
                        }
                    }
                    activeUploadNanos += System.nanoTime() - started
                    completedBytes += source.size
                    _uiState.value = _uiState.value.copy(selectedFiles = _uiState.value.selectedFiles - selected[index])
                }
                setTransfer(TransferUiState(TransferPhase.Completed, "All files saved on the computer.", total, total, 100))
            } catch (e: kotlinx.coroutines.CancellationException) {
                transferHttp.cancelActiveRequest()
                requestId?.let { id -> runCatching { withContext(Dispatchers.IO) { transferHttp.cancelTransfer(saved.address, saved.caCertificateDer, saved.token, id) } } }
                setTransfer(TransferUiState(TransferPhase.Cancelled, "Transfer cancelled."))
                throw e
            } catch (e: Throwable) {
                setTransfer(TransferUiState(TransferPhase.Error, transferFailureMessage(e)))
            }
        }
    }
    fun cancelTransfer() { transferHttp.cancelActiveRequest(); transferJob?.cancel() }
    fun dismissTransfer() { if (transferJob?.isActive != true) setTransfer(TransferUiState()) }
    private fun setTransfer(value: TransferUiState) { _uiState.value = _uiState.value.copy(transfer = value) }
    fun clearNotice() { _uiState.value = _uiState.value.copy(notice = null) }
    fun showNotice(message: String) { _uiState.value = _uiState.value.copy(notice = message) }

    override fun onCleared() {
        transferHttp.cancelActiveRequest()
        repository.cancelIncomingDownload()
        super.onCleared()
    }

    private fun restoreConnection() {
        val saved = repository.savedConnection() ?: return
        updateConnection { it.copy(addressDraft = saved.address, selectedCaDer = saved.caCertificateDer,
            selectedCaSha256 = saved.caSha256, selectedCaAddress = saved.address, trustedFingerprint = saved.caSha256,
            fingerprintConfirmation = saved.caSha256,
            phase = ConnectionPhase.PairingRequired) }
        if (saved.token.isNotBlank()) retryConnection()
    }

    private fun updateConnection(transform: (ConnectionUiState) -> ConnectionUiState) {
        _uiState.value = _uiState.value.copy(connection = transform(_uiState.value.connection))
    }

    private fun safeMessage(error: Throwable): String = when (error) {
        is ConnectionException -> error.message.orEmpty()
        else -> "Could not complete the connection. Check the server and try again."
    }

    private fun ContentResolver.readSmallDocument(uri: Uri): ByteArray {
        openInputStream(uri)?.use { input ->
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(4096)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                if (output.size() + count > MAX_CA_FILE_BYTES) throw IllegalArgumentException("Certificate file too large")
                output.write(buffer, 0, count)
            }
            return output.toByteArray()
        }
        throw IllegalArgumentException("Certificate could not be opened")
    }

    private fun ContentResolver.describe(uri: Uri): PickedFile? = runCatching {
        var name: String? = null
        var size: Long? = null
        query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (nameIndex >= 0) name = cursor.getString(nameIndex)
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) size = cursor.getLong(sizeIndex)
            }
        }
        PickedFile(uri.toString(), name?.takeIf(String::isNotBlank) ?: uri.lastPathSegment ?: "Selected file", size, getType(uri))
    }.getOrNull()

    class Factory(private val application: Application) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(DevDropViewModel::class.java))
            return DevDropViewModel(application) as T
        }
    }

    private companion object { const val MAX_CA_FILE_BYTES = 1_048_576 }
}
