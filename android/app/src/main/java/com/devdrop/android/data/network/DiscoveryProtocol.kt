package com.devdrop.android.data.network

import com.devdrop.android.data.model.DiscoveredServer
import java.net.InetAddress
import java.security.SecureRandom

const val DISCOVERY_PORT = 8766
const val DISCOVERY_MAGIC = "DEVDROP_DISCOVERY_V1"

fun newDiscoveryNonce(random: SecureRandom = SecureRandom()): String = ByteArray(16).also(random::nextBytes)
    .joinToString("") { "%02x".format(it) }

fun makeDiscoveryQuery(nonce: String): ByteArray {
    require(nonce.matches(Regex("[a-f0-9]{32}")))
    return "{\"magic\":\"$DISCOVERY_MAGIC\",\"action\":\"discover\",\"nonce\":\"$nonce\"}"
        .toByteArray(Charsets.US_ASCII)
}

/** Parse only authenticated-by-nonce UDP metadata. The packet source address wins over its claimed IP. */
fun parseDiscoveryResponse(data: ByteArray, expectedNonce: String, source: InetAddress): DiscoveredServer? {
    if (data.size > 2048) return null
    val fields = FlatJson.parse(data.toString(Charsets.US_ASCII)) ?: return null
    if (fields["magic"] != DISCOVERY_MAGIC || fields["action"] != "response" || fields["nonce"] != expectedNonce) return null
    val port = fields["port"]?.toIntOrNull()?.takeIf { it in 1..65535 } ?: return null
    val name = fields["name"]?.filterNot { it.isISOControl() }?.trim()?.take(80).orEmpty().ifBlank { "Dev-Drop server" }
    val host = source.hostAddress?.substringBefore('%')?.takeIf(String::isNotBlank) ?: return null
    val formattedHost = if (host.contains(':')) "[$host]" else host
    return DiscoveredServer(name, "https://$formattedHost:$port")
}

/** Minimal strict flat-object JSON reader for this protocol's scalar discovery fields. */
internal object FlatJson {
    fun parse(source: String): Map<String, String>? {
        var i = 0
        fun ws() { while (i < source.length && source[i].isWhitespace()) i++ }
        fun string(): String? {
            if (i >= source.length || source[i++] != '"') return null
            val out = StringBuilder()
            while (i < source.length) {
                val c = source[i++]
                when {
                    c == '"' -> return out.toString()
                    c == '\\' -> {
                        if (i >= source.length) return null
                        when (val escaped = source[i++]) {
                            '"', '\\', '/' -> out.append(escaped)
                            'b' -> out.append('\b')
                            'f' -> out.append('\u000c')
                            'n' -> out.append('\n')
                            'r' -> out.append('\r')
                            't' -> out.append('\t')
                            'u' -> {
                                if (i + 4 > source.length) return null
                                val code = source.substring(i, i + 4).toIntOrNull(16) ?: return null
                                out.append(code.toChar()); i += 4
                            }
                            else -> return null
                        }
                    }
                    c.code < 0x20 -> return null
                    else -> out.append(c)
                }
            }
            return null
        }
        ws(); if (i >= source.length || source[i++] != '{') return null
        val result = linkedMapOf<String, String>()
        ws()
        while (i < source.length && source[i] != '}') {
            val key = string() ?: return null
            ws(); if (i >= source.length || source[i++] != ':') return null
            ws()
            val value = if (source.getOrNull(i) == '"') string() ?: return null else when {
                source.startsWith("true", i) -> "true".also { i += 4 }
                source.startsWith("false", i) -> "false".also { i += 5 }
                source.startsWith("null", i) -> "null".also { i += 4 }
                else -> {
                    val start = i
                    while (i < source.length && source[i] in '0'..'9') i++
                    if (i == start) return null
                    source.substring(start, i)
                }
            }
            if (result.put(key, value) != null) return null
            ws()
            if (source.getOrNull(i) == ',') { i++; ws() } else break
        }
        if (source.getOrNull(i) != '}') return null
        i++; ws()
        return result.takeIf { i == source.length }
    }
}
