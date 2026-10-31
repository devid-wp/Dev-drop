package com.devdrop.android.data.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import com.devdrop.android.data.model.TrustedConnection
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Encrypts the session token, CA and server address with an Android Keystore AES-GCM key. */
class SecureConnectionStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("trusted_connection_v1", Context.MODE_PRIVATE)

    @Synchronized
    fun load(): TrustedConnection? = runCatching {
        val packed = Base64.decode(prefs.getString(DATA_KEY, null) ?: return null, Base64.NO_WRAP)
        require(packed.size > IV_BYTES)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, getKey(), GCMParameterSpec(128, packed, 0, IV_BYTES))
        val clear = cipher.doFinal(packed, IV_BYTES, packed.size - IV_BYTES).toString(Charsets.UTF_8)
        val fields = clear.split('\n', limit = 5)
        if (fields.size != 5) return null
        TrustedConnection(
            address = fields[0], caCertificateDer = Base64.decode(fields[1], Base64.NO_WRAP),
            caSha256 = fields[2], token = fields[3], serverName = fields[4],
        )
    }.getOrNull()

    @Synchronized
    fun save(connection: TrustedConnection) {
        val clear = listOf(connection.address, Base64.encodeToString(connection.caCertificateDer, Base64.NO_WRAP),
            connection.caSha256, connection.token, connection.serverName).joinToString("\n").toByteArray(Charsets.UTF_8)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getKey())
        val encrypted = cipher.iv + cipher.doFinal(clear)
        check(prefs.edit().putString(DATA_KEY, Base64.encodeToString(encrypted, Base64.NO_WRAP)).commit())
    }

    @Synchronized
    fun clear() {
        prefs.edit().remove(DATA_KEY).commit()
        runCatching { keyStore().deleteEntry(KEY_ALIAS) }
    }

    @Synchronized
    fun clearSession() {
        val current = load() ?: return
        save(current.copy(token = ""))
    }

    private fun getKey(): SecretKey {
        val store = keyStore()
        (store.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE).run {
            init(KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build())
            generateKey()
        }
    }

    private fun keyStore(): KeyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    private companion object {
        const val DATA_KEY = "trusted_connection"
        const val KEY_ALIAS = "devdrop.android.connection.aesgcm.v1"
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
    }
}
