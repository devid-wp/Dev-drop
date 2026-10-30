package com.devdrop.android.data

import android.app.Application
import android.content.ContentResolver
import android.provider.OpenableColumns
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class DevDropUiState(
    val selectedFiles: List<PickedFile> = emptyList(),
    val notice: String? = null,
)

class DevDropViewModel(application: Application) : AndroidViewModel(application) {
    private val _uiState = MutableStateFlow(DevDropUiState())
    val uiState: StateFlow<DevDropUiState> = _uiState.asStateFlow()

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

    fun removeFile(file: PickedFile) {
        _uiState.value = _uiState.value.copy(selectedFiles = _uiState.value.selectedFiles - file)
    }

    fun clearNotice() {
        _uiState.value = _uiState.value.copy(notice = null)
    }

    fun showNotice(message: String) {
        _uiState.value = _uiState.value.copy(notice = message)
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
        PickedFile(
            uri = uri.toString(),
            name = name?.takeIf(String::isNotBlank) ?: uri.lastPathSegment ?: "Selected file",
            sizeBytes = size,
            mimeType = getType(uri),
        )
    }.getOrNull()

    class Factory(private val application: Application) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
            require(modelClass.isAssignableFrom(DevDropViewModel::class.java))
            return DevDropViewModel(application) as T
        }
    }
}
