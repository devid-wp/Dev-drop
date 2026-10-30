package com.devdrop.android.ui.screens.send

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.devdrop.android.data.PickedFile
import com.devdrop.android.data.formatFileSize
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun SendScreen(
    files: List<PickedFile>,
    onPickPhotos: () -> Unit,
    onPickDocuments: () -> Unit,
    onRemove: (PickedFile) -> Unit,
) {
    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        ScreenHeader("Send", "Choose files for a nearby device")
        Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            shape = RoundedCornerShape(18.dp)) {
            Text("File transfer is not connected yet. You can select files now; sending stays disabled until a trusted server is connected.",
                Modifier.padding(16.dp), style = MaterialTheme.typography.bodyMedium)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = onPickPhotos, modifier = Modifier.weight(1f)) {
                DropIcon(DropIconKind.Photos)
                Text("Photos", Modifier.padding(start = 7.dp))
            }
            OutlinedButton(onClick = onPickDocuments, modifier = Modifier.weight(1f)) {
                DropIcon(DropIconKind.Files)
                Text("Browse files", Modifier.padding(start = 7.dp))
            }
        }
        if (files.isEmpty()) {
            Column(Modifier.weight(1f).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center) {
                Text("Nothing selected", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                Text("Choose photos or browse your files to get started.", color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium)
            }
        } else {
            Text("Selected files · ${files.size}", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(files, key = PickedFile::uri) { file ->
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                        shape = RoundedCornerShape(17.dp)) {
                        Row(Modifier.fillMaxWidth().padding(start = 15.dp, end = 10.dp, top = 14.dp, bottom = 14.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(file.name, style = MaterialTheme.typography.titleSmall, maxLines = 2)
                                Text(formatFileSize(file.sizeBytes), style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            androidx.compose.material3.IconButton(onClick = { onRemove(file) },
                                modifier = Modifier.semanticsDescription("Remove ${file.name}")) {
                                DropIcon(DropIconKind.Remove, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
            OutlinedButton(onClick = {}, enabled = false, modifier = Modifier.fillMaxWidth()) {
                Text("Choose recipient")
            }
            Button(onClick = {}, enabled = false, modifier = Modifier.fillMaxWidth()) {
                Text("Connect to a server to send")
            }
        }
    }
}

private fun Modifier.semanticsDescription(label: String): Modifier =
    this.then(Modifier.semantics { contentDescription = label })
