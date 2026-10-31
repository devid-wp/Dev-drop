package com.devdrop.android.data.network

import java.net.URI

object ServerAddress {
    fun normalize(raw: String): String? = runCatching {
        val uri = URI(raw.trim())
        if (!uri.isAbsolute || !uri.scheme.equals("https", ignoreCase = true) || uri.host.isNullOrBlank()) return null
        if (uri.rawUserInfo != null || uri.rawQuery != null || uri.rawFragment != null) return null
        if (uri.rawPath.isNotEmpty() && uri.rawPath != "/") return null
        if (uri.port !in -1..65535 || uri.port == 0) return null
        val host = uri.host.lowercase()
        val port = if (uri.port == -1) 443 else uri.port
        val bracketedHost = if (host.contains(':')) "[$host]" else host
        "https://$bracketedHost:$port"
    }.getOrNull()
}
