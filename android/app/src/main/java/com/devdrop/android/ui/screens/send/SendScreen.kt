package com.devdrop.android.ui.screens.send

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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.devdrop.android.data.PickedFile
import com.devdrop.android.data.formatFileSize
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun SendScreen(files: List<PickedFile>, onPickPhotos: () -> Unit, onPickDocuments: () -> Unit, onRemove: (PickedFile) -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp)) {
        ScreenHeader("Send files", "Choose what you want to share")

        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(24.dp)) {
            Column(Modifier.fillMaxWidth().padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(22.dp)) {
                    androidx.compose.foundation.layout.Box(Modifier.padding(18.dp)) {
                        DropIcon(DropIconKind.Files, modifier = Modifier.height(30.dp), tint = MaterialTheme.colorScheme.primary)
                    }
                }
                Spacer(Modifier.height(14.dp))
                Text("Add files to your queue", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(5.dp))
                Text("Photos, videos, and documents", style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(18.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(onClick = onPickPhotos, modifier = Modifier.weight(1f).height(48.dp), shape = CircleShape) {
                        DropIcon(DropIconKind.Photos)
                        Text("Photos", Modifier.padding(start = 8.dp))
                    }
                    OutlinedButton(onClick = onPickDocuments, modifier = Modifier.weight(1f).height(48.dp), shape = CircleShape) {
                        DropIcon(DropIconKind.Files)
                        Text("Browse", Modifier.padding(start = 8.dp))
                    }
                }
            }
        }

        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Selected files", style = MaterialTheme.typography.titleLarge)
            Spacer(Modifier.weight(1f))
            Text(files.size.toString().padStart(2, '0'), style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary)
        }
        if (files.isEmpty()) {
            Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(20.dp)) {
                Column(Modifier.fillMaxWidth().padding(vertical = 26.dp, horizontal = 20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("Your queue is empty", style = MaterialTheme.typography.titleMedium)
                    Spacer(Modifier.height(5.dp))
                    Text("Choose items above to see them here.", style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                files.forEach { file ->
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), shape = RoundedCornerShape(18.dp)) {
                        Row(Modifier.fillMaxWidth().padding(start = 14.dp, end = 8.dp, top = 12.dp, bottom = 12.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(12.dp)) {
                                androidx.compose.foundation.layout.Box(Modifier.padding(10.dp)) {
                                    DropIcon(DropIconKind.Files, tint = MaterialTheme.colorScheme.primary)
                                }
                            }
                            Column(Modifier.weight(1f).padding(horizontal = 12.dp)) {
                                Text(file.name, style = MaterialTheme.typography.titleSmall, maxLines = 2)
                                Text(formatFileSize(file.sizeBytes), style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            androidx.compose.material3.IconButton(onClick = { onRemove(file) },
                                modifier = Modifier.semantics { contentDescription = "Remove ${file.name}" }) {
                                DropIcon(DropIconKind.Remove, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }
        }
        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(18.dp)) {
            Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                Text("Recipient", style = MaterialTheme.typography.titleSmall)
                Text("Connect to a server to discover devices.", style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Button(onClick = {}, enabled = false, modifier = Modifier.fillMaxWidth().height(54.dp), shape = CircleShape,
            colors = ButtonDefaults.buttonColors(disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant,
                disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant)) {
            Text("Send unavailable")
        }
        Text("Server connection and file transfer are not configured yet.", Modifier.fillMaxWidth(),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center)
    }
}
