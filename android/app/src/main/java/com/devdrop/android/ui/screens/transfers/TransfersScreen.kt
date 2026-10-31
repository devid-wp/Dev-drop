package com.devdrop.android.ui.screens.transfers

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.devdrop.android.data.IncomingDownloadUiState
import com.devdrop.android.data.IncomingPhase
import com.devdrop.android.data.TransferPhase
import com.devdrop.android.data.TransferUiState
import com.devdrop.android.data.formatFileSize
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun TransfersScreen(
    transfer: TransferUiState,
    incomingDownload: IncomingDownloadUiState?,
    pendingOffers: Int,
    onCancelSend: () -> Unit,
    onCancelReceive: () -> Unit,
    onOpenIncoming: () -> Unit,
) {
    val hasActivity = transfer.phase != TransferPhase.Idle || incomingDownload != null
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp)) {
        ScreenHeader("Transfers", "Activity to and from this device")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("All activity", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.weight(1f))
            Text(if (hasActivity) "${1 + if (transfer.phase != TransferPhase.Idle && incomingDownload != null) 1 else 0}" else "0",
                style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        OutlinedButton(onClick = onOpenIncoming, modifier = Modifier.fillMaxWidth(), shape = CircleShape) {
            Text(if (pendingOffers > 0) "Incoming files · $pendingOffers waiting" else "Incoming files")
        }
        if (transfer.phase != TransferPhase.Idle) {
            Surface(Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(24.dp)) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Sending to computer", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                    Text(transfer.message.orEmpty(), style = MaterialTheme.typography.titleMedium)
                    if (transfer.phase == TransferPhase.Sending) Text("${transfer.percent}% · ${formatFileSize(transfer.bytesSent)} of ${formatFileSize(transfer.totalBytes)} · ${transfer.bytesPerSecond?.let { formatFileSize(it) + "/s" } ?: "Speed pending"}${transfer.etaSeconds?.let { " · ETA ${it}s" } ?: ""}", style = MaterialTheme.typography.bodySmall)
                    if (transfer.phase in setOf(TransferPhase.Preparing, TransferPhase.WaitingApproval, TransferPhase.Sending))
                        OutlinedButton(onClick = onCancelSend, shape = CircleShape) { Text("Cancel send") }
                }
            }
        }
        incomingDownload?.let { state ->
            Surface(Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(24.dp)) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Receiving from computer", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                    Text(state.offer.filename, style = MaterialTheme.typography.titleMedium)
                    Text(state.message, style = MaterialTheme.typography.bodyMedium,
                        color = if (state.phase == IncomingPhase.Error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
                    if (state.phase == IncomingPhase.Downloading) {
                        LinearProgressIndicator(progress = { state.percent / 100f }, modifier = Modifier.fillMaxWidth())
                        Text("${state.percent}% · ${formatFileSize(state.bytesReceived)} of ${formatFileSize(state.totalBytes)} · ${state.bytesPerSecond?.let { formatFileSize(it) + "/s" } ?: "Calculating speed…"}${state.etaSeconds?.let { " · ETA ${it}s" } ?: ""}", style = MaterialTheme.typography.bodySmall)
                    }
                    if (state.phase in setOf(IncomingPhase.ChoosingDestination, IncomingPhase.Preparing, IncomingPhase.Downloading))
                        OutlinedButton(onClick = onCancelReceive, shape = CircleShape) { Text("Cancel download") }
                }
            }
        }
        if (!hasActivity) {
            Surface(Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(24.dp)) {
                Column(Modifier.fillMaxWidth().padding(horizontal = 26.dp, vertical = 34.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("No active transfers", style = MaterialTheme.typography.titleMedium)
                    Text("Incoming offers and transfer activity will appear here.", Modifier.padding(top = 6.dp),
                        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}
