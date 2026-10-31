package com.devdrop.android.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.devdrop.android.BuildConfig
import com.devdrop.android.ui.components.ConnectionStatus
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun SettingsScreen() {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp)) {
        ScreenHeader("Settings", "Connection and app information")
        Text("CONNECTION", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(22.dp)) {
            Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(18.dp)) {
                Row(Modifier.fillMaxWidth()) {
                    DropIcon(DropIconKind.Storage, tint = MaterialTheme.colorScheme.primary)
                    Column(Modifier.weight(1f).padding(start = 14.dp)) {
                        Text("Dev-Drop server", style = MaterialTheme.typography.titleMedium)
                        Text("No server address configured", style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                Row(Modifier.fillMaxWidth()) {
                    DropIcon(DropIconKind.Security, tint = MaterialTheme.colorScheme.primary)
                    Column(Modifier.weight(1f).padding(start = 14.dp)) {
                        Text("TLS trust", style = MaterialTheme.typography.titleMedium)
                        Text("Not established", style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                ConnectionStatus("Backend integration unavailable")
            }
        }
        Text("ABOUT", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(22.dp)) {
            Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row {
                    DropIcon(DropIconKind.Info, tint = MaterialTheme.colorScheme.primary)
                    Text("About Dev-Drop", Modifier.padding(start = 12.dp), style = MaterialTheme.typography.titleMedium)
                }
                Text("A local-network file sharing client.", style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(1.dp))
                Text("Version ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
