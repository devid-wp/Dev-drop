package com.devdrop.android.ui.screens.device

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun DeviceDetailsScreen() {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp)) {
        ScreenHeader("Device details", "Connection information")
        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(28.dp)) {
            Column(Modifier.fillMaxWidth().padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(24.dp)) {
                    androidx.compose.foundation.layout.Box(Modifier.padding(20.dp)) {
                        DropIcon(DropIconKind.Computer, modifier = Modifier.height(32.dp), tint = MaterialTheme.colorScheme.primary)
                    }
                }
                Spacer(Modifier.height(18.dp))
                Text("No device selected", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(7.dp))
                Text("Device discovery is not connected. Details will be available after a server reports a real device.",
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center)
            }
        }
        Text("Network, trust, and transfer information will appear here when provided by the connected server.",
            Modifier.fillMaxWidth().padding(horizontal = 8.dp), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
    }
}
