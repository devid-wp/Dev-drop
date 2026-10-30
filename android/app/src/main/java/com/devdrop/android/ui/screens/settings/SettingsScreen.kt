package com.devdrop.android.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
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
    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        ScreenHeader("Settings", "Connection and app information")
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            SettingRow(DropIconKind.Storage, "Server", "Not connected")
            SettingRow(DropIconKind.Security, "TLS trust", "Not configured")
        }
        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(21.dp)) {
            Column(Modifier.fillMaxWidth().padding(17.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row {
                    DropIcon(DropIconKind.Info, tint = MaterialTheme.colorScheme.primary)
                    Text("About Dev-Drop", Modifier.padding(start = 10.dp), style = MaterialTheme.typography.titleMedium)
                }
                Text("A private, local-network file sharing client.", style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(2.dp))
                Text("Version ${BuildConfig.VERSION_NAME}", style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        ConnectionStatus("Backend integration not configured")
    }
}

@Composable
private fun SettingRow(icon: DropIconKind, title: String, value: String) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(18.dp)) {
        Row(Modifier.fillMaxWidth().padding(16.dp)) {
            DropIcon(icon, tint = MaterialTheme.colorScheme.primary)
            Column(Modifier.padding(start = 12.dp)) {
                Text(title, style = MaterialTheme.typography.titleSmall)
                Text(value, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
