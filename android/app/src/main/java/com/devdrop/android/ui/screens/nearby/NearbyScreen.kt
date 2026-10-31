package com.devdrop.android.ui.screens.nearby

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.devdrop.android.data.model.ConnectionPhase
import com.devdrop.android.data.model.ConnectionUiState
import com.devdrop.android.data.model.DiscoveredServer
import com.devdrop.android.ui.components.ConnectionStatus
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun NearbyScreen(
    connection: ConnectionUiState,
    onSearch: () -> Unit,
    onScanQr: () -> Unit,
    onAddressChanged: (String) -> Unit,
    onConnectAddress: () -> Unit,
    onSelectServer: (DiscoveredServer) -> Unit,
    onOpenDetails: () -> Unit,
) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp)) {
        ScreenHeader("Dev-Drop", "Connect to your local server")
        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(20.dp)) {
            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                val statusLabel = when (connection.phase) {
                    ConnectionPhase.Connected -> "Connected · ${connection.connectedName ?: "Dev-Drop server"}"
                    ConnectionPhase.Connecting -> "Connecting securely…"
                    ConnectionPhase.Scanning -> "Searching local network…"
                    ConnectionPhase.Unavailable -> "Server unavailable"
                    ConnectionPhase.Error -> "Connection needs attention"
                    else -> "Not connected"
                }
                ConnectionStatus(statusLabel, connected = connection.phase == ConnectionPhase.Connected)
                if (connection.phase == ConnectionPhase.Connected) {
                    Text(connection.connectedAddress.orEmpty(), style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    TextButton(onClick = onOpenDetails, modifier = Modifier.semantics { contentDescription = "Open connected server details" }) {
                        Text("Connection details")
                    }
                } else {
                    Text("Discovery is local-network metadata. A server is trusted only after CA verification and pairing.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(11.dp)) {
            Text("Find your server", style = MaterialTheme.typography.headlineSmall)
            Button(onClick = onSearch, enabled = connection.phase != ConnectionPhase.Scanning,
                modifier = Modifier.fillMaxWidth().height(52.dp), shape = CircleShape,
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary, contentColor = MaterialTheme.colorScheme.onPrimary)) {
                DropIcon(DropIconKind.Search, tint = MaterialTheme.colorScheme.onPrimary)
                Text(if (connection.phase == ConnectionPhase.Scanning) "Searching…" else "Search local network", Modifier.padding(start = 10.dp))
            }
            OutlinedButton(onClick = onScanQr, modifier = Modifier.fillMaxWidth().height(50.dp), shape = CircleShape) {
                DropIcon(DropIconKind.Nearby, tint = MaterialTheme.colorScheme.primary)
                Text("Scan server QR", Modifier.padding(start = 10.dp))
            }
        }

        if (connection.phase == ConnectionPhase.NoDevices) {
            EmptyDiscovery("No Dev-Drop servers found", "Check that the computer and phone are on the same local network.")
        }
        if (connection.phase == ConnectionPhase.ServersFound) {
            Text("Servers found · ${connection.servers.size}", style = MaterialTheme.typography.titleLarge)
            connection.servers.forEach { server ->
                Surface(onClick = { onSelectServer(server) }, color = MaterialTheme.colorScheme.surface,
                    shape = RoundedCornerShape(19.dp)) {
                    Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                        Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(13.dp)) {
                            androidx.compose.foundation.layout.Box(Modifier.padding(11.dp)) {
                                DropIcon(DropIconKind.Computer, tint = MaterialTheme.colorScheme.primary)
                            }
                        }
                        Column(Modifier.weight(1f).padding(start = 12.dp)) {
                            Text(server.name, style = MaterialTheme.typography.titleMedium)
                            Text(server.address, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text("Discovered · not yet trusted", style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text("›", style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.primary)
                    }
                }
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Connect by address", style = MaterialTheme.typography.titleLarge)
            OutlinedTextField(value = connection.addressDraft, onValueChange = onAddressChanged,
                modifier = Modifier.fillMaxWidth(), label = { Text("HTTPS server address") },
                placeholder = { Text("https://192.168.1.50:8765") }, singleLine = true,
                supportingText = { Text("Use the address shown by the Dev-Drop computer.") })
            OutlinedButton(onClick = onConnectAddress, enabled = connection.addressDraft.isNotBlank(),
                modifier = Modifier.fillMaxWidth().height(50.dp), shape = CircleShape) {
                Text("Continue to secure setup")
            }
        }
        connection.errorMessage?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
    }
}

@Composable
private fun EmptyDiscovery(title: String, message: String) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(24.dp)) {
        Column(Modifier.fillMaxWidth().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            DropIcon(DropIconKind.Nearby, modifier = Modifier.height(30.dp), tint = MaterialTheme.colorScheme.primary)
            Spacer(Modifier.height(12.dp))
            Text(title, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(5.dp))
            Text(message, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
        }
    }
}
