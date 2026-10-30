package com.devdrop.android.data

data class PickedFile(
    val uri: String,
    val name: String,
    val sizeBytes: Long?,
    val mimeType: String?,
)

fun formatFileSize(bytes: Long?): String {
    if (bytes == null || bytes < 0) return "Size unavailable"
    if (bytes < 1024) return "$bytes B"
    val units = listOf("KB", "MB", "GB", "TB")
    var value = bytes.toDouble()
    var unit = -1
    do {
        value /= 1024.0
        unit++
    } while (value >= 1024 && unit < units.lastIndex)
    return "%.1f %s".format(java.util.Locale.ROOT, value, units[unit])
}
