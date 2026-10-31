package com.devdrop.android.data.network

import android.content.Context
import android.net.wifi.WifiManager
import com.devdrop.android.data.model.DiscoveredServer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException
import java.security.SecureRandom

class DevDropDiscoveryClient(context: Context) {
    private val appContext = context.applicationContext

    suspend fun scan(): List<DiscoveredServer> = withContext(Dispatchers.IO) {
        val lock = runCatching {
            (appContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager)
                ?.createMulticastLock("devdrop-discovery")?.apply { setReferenceCounted(false); acquire() }
        }.getOrNull()
        try {
            val nonce = newDiscoveryNonce(SecureRandom())
            val query = makeDiscoveryQuery(nonce)
            val found = linkedMapOf<String, DiscoveredServer>()
            DatagramSocket().use { socket ->
                socket.broadcast = true
                socket.soTimeout = 350
                socket.send(DatagramPacket(query, query.size, InetAddress.getByName("255.255.255.255"), DISCOVERY_PORT))
                val deadline = System.nanoTime() + 1_400_000_000L
                while (System.nanoTime() < deadline) {
                    val packetBuffer = ByteArray(2048)
                    val packet = DatagramPacket(packetBuffer, packetBuffer.size)
                    try {
                        socket.receive(packet)
                    } catch (_: SocketTimeoutException) {
                        continue
                    }
                    parseDiscoveryResponse(packet.data.copyOf(packet.length), nonce, packet.address)?.let {
                        found[it.address] = it
                    }
                }
            }
            found.values.toList()
        } finally {
            if (lock?.isHeld == true) runCatching { lock.release() }
        }
    }
}
