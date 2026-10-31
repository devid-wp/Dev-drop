package com.devdrop.android.ui.screens.transfers

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.EmptyState
import com.devdrop.android.ui.components.ScreenHeader
import com.devdrop.android.data.TransferUiState
import com.devdrop.android.data.TransferPhase
import com.devdrop.android.data.formatFileSize

@Composable
fun TransfersScreen(transfer: TransferUiState, onCancel: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp)) {
        ScreenHeader("Transfers", "Activity from this device")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("All activity", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.weight(1f))
            Text(if (transfer.phase == TransferPhase.Idle) "0" else "1", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (transfer.phase != TransferPhase.Idle) {
            Surface(Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(26.dp)) {
                Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(transfer.message.orEmpty(), style = MaterialTheme.typography.titleMedium)
                    if (transfer.phase == TransferPhase.Sending) Text("${transfer.percent}% · ${formatFileSize(transfer.bytesSent)} of ${formatFileSize(transfer.totalBytes)} · ${transfer.bytesPerSecond?.let { formatFileSize(it) + "/s" } ?: "Speed pending"}${transfer.etaSeconds?.let { " · ETA ${it}s" } ?: ""}")
                    if (transfer.phase in setOf(TransferPhase.Preparing, TransferPhase.WaitingApproval, TransferPhase.Sending)) androidx.compose.material3.OutlinedButton(onClick = onCancel) { Text("Cancel transfer") }
                }
            }
        }
        Surface(Modifier.fillMaxWidth(), color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(26.dp)) {
            EmptyState(
                title = "Nothing here yet",
                message = "Transfers will appear here after the app connects to a Dev-Drop server.",
                modifier = Modifier.padding(horizontal = 26.dp, vertical = 52.dp),
                illustration = {
                    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(22.dp)) {
                        androidx.compose.foundation.layout.Box(Modifier.padding(18.dp)) {
                            DropIcon(DropIconKind.Transfers, tint = MaterialTheme.colorScheme.primary)
                        }
                    }
                },
            )
        }
    }
}
