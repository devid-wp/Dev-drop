package com.devdrop.android.ui.screens.connection

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
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.devdrop.android.data.model.ConnectionPhase
import com.devdrop.android.data.model.ConnectionUiState
import com.devdrop.android.data.network.ServerAddress
import com.devdrop.android.data.security.ServerTrust
import com.devdrop.android.ui.components.ConnectionStatus
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun ConnectionSetupScreen(
    state: ConnectionUiState,
    onAddressChanged: (String) -> Unit,
    onPickCertificate: () -> Unit,
    onFingerprintChanged: (String) -> Unit,
    onPairingCodeChanged: (String) -> Unit,
    onPair: () -> Unit,
    onCancelPairing: () -> Unit,
    onCheck: () -> Unit,
    onDisconnect: () -> Unit,
    onBack: () -> Unit,
) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp)) {
        Row(Modifier.fillMaxWidth()) {
            TextButton(onClick = onBack) { Text("‹  Nearby") }
        }
        ScreenHeader("Secure connection", "Verify the server, then pair this device")

        if (state.phase == ConnectionPhase.Connected) {
            Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(24.dp)) {
                Column(Modifier.fillMaxWidth().padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                    ConnectionStatus("Connected · ${state.connectedName ?: "Dev-Drop server"}", connected = true)
                    DetailLine("Address", state.connectedAddress.orEmpty())
                    DetailLine("Trust anchor", "CA SHA-256 verified")
                    state.trustedFingerprint?.let { DetailLine("CA fingerprint", it, mono = true) }
                    OutlinedButton(onClick = onCheck, modifier = Modifier.fillMaxWidth().height(48.dp), shape = CircleShape) {
                        Text("Check connection")
                    }
                    TextButton(onClick = onDisconnect, modifier = Modifier.fillMaxWidth()) { Text("Disconnect") }
                }
            }
        } else if (state.qrPairing) {
            StepCard("01", "Secure PC connection", "The scanned QR carries a one use token and the computer's public CA. Android validates the QR fingerprints, certificate chain, and server hostname before sending it.") {
                DetailLine("HTTPS address", state.addressDraft)
                state.selectedCaSha256?.let { DetailLine("QR CA SHA-256", it, mono = true) }
            }
            StepCard("02", "Confirm this phone", "Enter this six digit number on the computer only when its local screen shows this phone and address. The number is a human check, not an authentication secret.") {
                Text(state.pairingCode, style = MaterialTheme.typography.headlineLarge, fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.primary)
                Text(if (state.phase == ConnectionPhase.Connecting) "Waiting for approval on the computer…" else "Ready to request pairing",
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            state.errorMessage?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error) }
            if (state.phase == ConnectionPhase.Connecting) {
                OutlinedButton(onClick = onCancelPairing, modifier = Modifier.fillMaxWidth().height(50.dp), shape = CircleShape) { Text("Cancel pairing") }
            } else if (state.phase == ConnectionPhase.Error) {
                OutlinedButton(onClick = onBack, modifier = Modifier.fillMaxWidth().height(50.dp), shape = CircleShape) { Text("Scan a fresh QR") }
            } else {
                Button(onClick = onPair, enabled = state.phase != ConnectionPhase.Connecting,
                    modifier = Modifier.fillMaxWidth().height(54.dp), shape = CircleShape) { Text("Request PC approval") }
            }
        } else {
            StepCard("01", "Server address", "A QR code contains only the HTTPS address. It does not establish trust or carry a pairing code.") {
                OutlinedTextField(value = state.addressDraft, onValueChange = onAddressChanged,
                    modifier = Modifier.fillMaxWidth(), singleLine = true, label = { Text("HTTPS address") })
            }

            StepCard("02", "Verify server certificate", "Select the public CA certificate shared by the computer owner through a trusted channel. Compare its SHA-256 with the owner's independently displayed fingerprint.") {
                OutlinedButton(onClick = onPickCertificate, modifier = Modifier.fillMaxWidth().height(48.dp), shape = CircleShape) {
                    DropIcon(DropIconKind.Security, tint = MaterialTheme.colorScheme.primary)
                    Text(if (state.selectedCaSha256 == null) "Choose CA certificate" else "Choose a different CA", Modifier.padding(start = 9.dp))
                }
                state.selectedCaSha256?.let { fingerprint ->
                    Text("Selected CA · SHA-256", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(fingerprint, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.primary)
                    OutlinedTextField(value = state.fingerprintConfirmation, onValueChange = onFingerprintChanged,
                        modifier = Modifier.fillMaxWidth(), label = { Text("Owner-verified CA fingerprint") },
                        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii),
                        supportingText = { Text("Enter the 64 hexadecimal characters; colons are optional.") })
                }
            }

            StepCard("03", "Pair this device", "Enter the current 9-digit code shown on the Dev-Drop computer. It expires after five minutes; ask the owner to regenerate it after pairing. Each file transfer still needs separate owner approval.") {
                OutlinedTextField(value = state.pairingCode, onValueChange = onPairingCodeChanged,
                    modifier = Modifier.fillMaxWidth(), label = { Text("Pairing code") },
                    singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword))
            }

            state.errorMessage?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error) }
            Button(onClick = onPair, enabled = canPair(state), modifier = Modifier.fillMaxWidth().height(54.dp), shape = CircleShape,
                colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary, contentColor = MaterialTheme.colorScheme.onPrimary)) {
                Text(if (state.phase == ConnectionPhase.Connecting) "Verifying and pairing…" else "Verify & pair")
            }
            if (state.phase == ConnectionPhase.Unavailable) {
                TextButton(onClick = onCheck, modifier = Modifier.fillMaxWidth()) { Text("Check connection again") }
            }
            Text("No credentials are sent until HTTPS certificate-chain and hostname checks succeed.",
                Modifier.fillMaxWidth(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

private fun canPair(state: ConnectionUiState): Boolean {
    val caHash = state.selectedCaSha256 ?: return false
    return state.phase != ConnectionPhase.Connecting &&
        ServerAddress.normalize(state.addressDraft) != null &&
        ServerTrust.normalizeFingerprint(state.fingerprintConfirmation) == caHash &&
        state.pairingCode.matches(Regex("[0-9]{9}"))
}

@Composable
private fun StepCard(number: String, title: String, description: String, content: @Composable () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(22.dp)) {
        Column(Modifier.fillMaxWidth().padding(17.dp), verticalArrangement = Arrangement.spacedBy(11.dp)) {
            Row {
                Text(number, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                Text(title, Modifier.padding(start = 10.dp), style = MaterialTheme.typography.titleMedium)
            }
            Text(description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            content()
        }
    }
}

@Composable
private fun DetailLine(label: String, value: String, mono: Boolean = false) {
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyMedium,
            fontFamily = if (mono) FontFamily.Monospace else FontFamily.SansSerif)
        Spacer(Modifier.height(1.dp))
    }
}
