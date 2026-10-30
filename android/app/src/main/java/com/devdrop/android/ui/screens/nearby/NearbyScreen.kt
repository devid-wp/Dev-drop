package com.devdrop.android.ui.screens.nearby

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.devdrop.android.ui.components.ConnectionStatus
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.EmptyState
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun NearbyScreen(onSearch: () -> Unit, onOpenSettings: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(horizontal = 20.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp),
    ) {
        ScreenHeader("Dev-Drop", "Share files on your local network")
        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(22.dp)) {
            Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                ConnectionStatus("Server not connected")
                Text("Your devices stay on your network.", style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                OutlinedButton(onClick = onOpenSettings, modifier = Modifier.fillMaxWidth()) {
                    Text("Connection settings")
                }
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Nearby devices", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Box(Modifier.fillMaxWidth().weight(1f).background(MaterialTheme.colorScheme.surface, RoundedCornerShape(26.dp))) {
                EmptyState(
                    title = "No devices found",
                    message = "Connect to a Dev-Drop server to discover available devices.",
                    modifier = Modifier.align(Alignment.Center).padding(28.dp),
                    illustration = {
                        Box(Modifier.padding(bottom = 2.dp).background(MaterialTheme.colorScheme.surfaceVariant, CircleShape)
                            .padding(18.dp)) {
                            DropIcon(DropIconKind.Nearby, modifier = Modifier.height(32.dp), tint = MaterialTheme.colorScheme.primary)
                        }
                    },
                )
            }
        }
        Button(onClick = onSearch, modifier = Modifier.fillMaxWidth()) {
            DropIcon(DropIconKind.Search)
            Spacer(Modifier.width(8.dp))
            Text("Search for devices", Modifier.padding(start = 8.dp))
        }
    }
}
