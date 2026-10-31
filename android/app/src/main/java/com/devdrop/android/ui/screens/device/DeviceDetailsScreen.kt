package com.devdrop.android.ui.screens.device

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.devdrop.android.data.model.ConnectionPhase
import com.devdrop.android.data.model.ConnectionUiState
import com.devdrop.android.ui.components.ConnectionStatus
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun DeviceDetailsScreen(state: ConnectionUiState, onCheck: () -> Unit, onDisconnect: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp)) {
        ScreenHeader("Server details", state.connectedName ?: "Connection status")
        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(24.dp)) {
            Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                ConnectionStatus(if (state.phase == ConnectionPhase.Connected) "Connected" else "Server unavailable",
                    connected = state.phase == ConnectionPhase.Connected)
                Detail("Address", state.connectedAddress ?: "Not connected")
                Detail("Trust", if (state.trustedFingerprint != null) "Owner-verified CA" else "Not established")
                state.trustedFingerprint?.let { Detail("CA SHA-256", it) }
            }
        }
        state.errorMessage?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
        if (state.phase == ConnectionPhase.Connected) {
            OutlinedButton(onClick = onCheck, modifier = Modifier.fillMaxWidth()) { Text("Check server session") }
            TextButton(onClick = onDisconnect, modifier = Modifier.fillMaxWidth()) { Text("Disconnect on this phone") }
        }
    }
}

@Composable
private fun Detail(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}
