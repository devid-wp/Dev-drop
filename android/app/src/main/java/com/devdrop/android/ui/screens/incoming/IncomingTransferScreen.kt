package com.devdrop.android.ui.screens.incoming

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
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.devdrop.android.data.IncomingDownloadUiState
import com.devdrop.android.data.IncomingPhase
import com.devdrop.android.data.formatFileSize
import com.devdrop.android.data.model.IncomingFileOffer
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun IncomingTransferScreen(
    connected: Boolean,
    offers: List<IncomingFileOffer>,
    offersError: String?,
    download: IncomingDownloadUiState?,
    destinationPickerOpen: Boolean,
    onRefresh: () -> Unit,
    onBack: () -> Unit,
    onAccept: (IncomingFileOffer) -> Unit,
    onReject: (IncomingFileOffer) -> Unit,
    onCancelDownload: () -> Unit,
) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        ScreenHeader("Incoming files", "Review each offer before saving")
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = onBack, modifier = Modifier.weight(1f), shape = CircleShape) { Text("Back to transfers") }
            OutlinedButton(onClick = onRefresh, enabled = connected, modifier = Modifier.weight(1f), shape = CircleShape) { Text("Refresh") }
        }
        if (!connected) {
            EmptyCard("Connect to a computer", "Pair with a Dev-Drop server to receive file offers.")
        } else if (offersError != null && offers.isEmpty()) {
            EmptyCard("Offers unavailable", offersError)
        } else if (offers.none { it.status == "pending" }) {
            EmptyCard("No pending offers", "New files from the computer will appear here. Nothing is downloaded until you choose Accept & save.")
        }
        offersError?.takeIf { offers.isNotEmpty() }?.let {
            Text("Could not refresh offers: $it", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        }
        offers.forEach { offer -> OfferCard(offer, destinationPickerOpen, onAccept, onReject) }
        download?.let { DownloadCard(it, onCancelDownload) }
    }
}

@Composable
private fun OfferCard(offer: IncomingFileOffer, destinationPickerOpen: Boolean,
                      onAccept: (IncomingFileOffer) -> Unit, onReject: (IncomingFileOffer) -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(24.dp)) {
        Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(12.dp)) {
                    androidx.compose.foundation.layout.Box(Modifier.padding(10.dp)) {
                        DropIcon(DropIconKind.Files, tint = MaterialTheme.colorScheme.primary)
                    }
                }
                Column(Modifier.weight(1f).padding(start = 12.dp)) {
                    Text(offer.filename, style = MaterialTheme.typography.titleMedium, maxLines = 2)
                    Text(formatFileSize(offer.size), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            OfferMetadata("From", offer.sender)
            OfferMetadata("Offer", offer.statusLabel())
            OfferMetadata("Expires", offer.expiresLabel())
            if (offer.status == "pending") {
                Text("Accept & save opens Android's save picker. The server is accepted only after you choose a destination.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(onClick = { onReject(offer) }, enabled = !destinationPickerOpen,
                        modifier = Modifier.weight(1f), shape = CircleShape) { Text("Decline") }
                    Button(onClick = { onAccept(offer) }, enabled = !destinationPickerOpen,
                        modifier = Modifier.weight(1f), shape = CircleShape) { Text(if (destinationPickerOpen) "Choose destination…" else "Accept & save") }
                }
            }
        }
    }
}

@Composable
private fun DownloadCard(download: IncomingDownloadUiState, onCancel: () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(24.dp)) {
        Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
            Text(download.offer.filename, style = MaterialTheme.typography.titleMedium)
            Text(download.message, style = MaterialTheme.typography.bodyMedium,
                color = if (download.phase == IncomingPhase.Error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
            if (download.phase == IncomingPhase.Downloading) {
                LinearProgressIndicator(progress = { download.percent / 100f }, modifier = Modifier.fillMaxWidth())
                Text("${download.percent}% · ${formatFileSize(download.bytesReceived)} of ${formatFileSize(download.totalBytes)} · ${download.bytesPerSecond?.let { "${formatFileSize(it)}/s" } ?: "Calculating speed…"}${download.etaSeconds?.let { " · ETA ${it}s" } ?: ""}",
                    style = MaterialTheme.typography.bodySmall)
            }
            if (download.phase in setOf(IncomingPhase.ChoosingDestination, IncomingPhase.Preparing, IncomingPhase.Downloading)) {
                OutlinedButton(onClick = onCancel, modifier = Modifier.fillMaxWidth(), shape = CircleShape) { Text("Cancel download") }
            }
        }
    }
}

@Composable
private fun OfferMetadata(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Top) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, modifier = Modifier.weight(1f).padding(start = 16.dp), style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.End, maxLines = 2)
    }
}

@Composable
private fun EmptyCard(title: String, message: String) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(28.dp)) {
        Column(Modifier.fillMaxWidth().padding(26.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(20.dp)) {
                androidx.compose.foundation.layout.Box(Modifier.padding(16.dp)) {
                    DropIcon(DropIconKind.Transfers, modifier = Modifier.height(30.dp), tint = MaterialTheme.colorScheme.primary)
                }
            }
            Spacer(Modifier.height(14.dp))
            Text(title, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
            Spacer(Modifier.height(6.dp))
            Text(message, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center)
        }
    }
}

private fun IncomingFileOffer.statusLabel(): String = when (status) {
    "pending" -> "Waiting for your decision"
    "accepted" -> "Already accepted · ask the computer to resend if needed"
    "streaming" -> "Server is streaming this offer"
    "sent" -> "Server sent the data · local save is not confirmed here"
    "failed" -> "Server stream failed · ask the computer to resend"
    "expired" -> "Offer expired"
    "rejected" -> "Declined"
    "cancelled" -> "Cancelled by the sender"
    else -> status.replaceFirstChar { it.uppercase() }
}

private fun IncomingFileOffer.expiresLabel(): String {
    val seconds = (expiresAt - System.currentTimeMillis() / 1000.0).toLong()
    return if (seconds <= 0) "Expired" else "In ${seconds / 60}m ${seconds % 60}s"
}
