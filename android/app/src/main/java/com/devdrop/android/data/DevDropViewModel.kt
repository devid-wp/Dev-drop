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
import com.devdrop.android.data.model.reduceConnectionPhase
import com.devdrop.android.data.network.ServerAddress
import com.devdrop.android.data.repository.DefaultDevDropConnectionRepository
import com.devdrop.android.data.repository.DevDropConnectionRepository
import com.devdrop.android.data.security.ServerTrust
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class DevDropUiState(
    val selectedFiles: List<PickedFile> = emptyList(),
    val notice: String? = null,
    val connection: ConnectionUiState = ConnectionUiState(),
)

class DevDropViewModel(
    application: Application,
    private val repository: DevDropConnectionRepository = DefaultDevDropConnectionRepository(application),
) : AndroidViewModel(application) {
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
        viewModelScope.launch(Dispatchers.IO) {
            repository.disconnect()
            updateConnection { ConnectionUiState(phase = ConnectionPhase.Disconnected) }
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
    fun clearNotice() { _uiState.value = _uiState.value.copy(notice = null) }
    fun showNotice(message: String) { _uiState.value = _uiState.value.copy(notice = message) }

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
