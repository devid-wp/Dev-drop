package com.devdrop.android.ui.screens.nearby

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.devdrop.android.ui.components.ConnectionStatus
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun NearbyScreen(onSearch: () -> Unit, onOpenSettings: () -> Unit) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp),
    ) {
        ScreenHeader("Dev-Drop", "Private file sharing on your network")
        Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(20.dp)) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                ConnectionStatus("Server not connected")
                Spacer(Modifier.weight(1f))
                Text("TLS unavailable", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Nearby devices", style = MaterialTheme.typography.headlineSmall)
            Surface(color = MaterialTheme.colorScheme.surface, shape = RoundedCornerShape(28.dp)) {
                Column(Modifier.fillMaxWidth().padding(horizontal = 22.dp, vertical = 20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    RadarEmpty()
                    Spacer(Modifier.height(12.dp))
                    Text("No devices found", style = MaterialTheme.typography.titleLarge)
                    Spacer(Modifier.height(6.dp))
                    Text("Connect to a Dev-Drop server to discover available devices.",
                        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.fillMaxWidth(), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                    Spacer(Modifier.height(10.dp))
                    Text("Device discovery is not configured", style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        Button(
            onClick = onSearch,
            modifier = Modifier.fillMaxWidth().height(54.dp),
            shape = CircleShape,
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.primary, contentColor = MaterialTheme.colorScheme.onPrimary),
        ) {
            DropIcon(DropIconKind.Search, tint = MaterialTheme.colorScheme.onPrimary)
            Text("Search for devices", Modifier.padding(start = 10.dp))
        }
        Surface(onClick = onOpenSettings, color = Color.Transparent, shape = RoundedCornerShape(16.dp)) {
            Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                DropIcon(DropIconKind.Settings, tint = MaterialTheme.colorScheme.primary)
                Text("Configure server connection", Modifier.padding(start = 12.dp), style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.weight(1f))
                Text("›", style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun RadarEmpty() {
    val ringColor = MaterialTheme.colorScheme.outlineVariant.copy(alpha = .65f)
    Box(Modifier.size(204.dp).semantics { contentDescription = "No devices discovered" }, contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val stroke = Stroke(width = 1.dp.toPx())
            for (ratio in listOf(.42f, .68f, .94f)) {
                drawCircle(ringColor, size.minDimension * ratio / 2f, style = stroke)
            }
        }
        Box(Modifier.size(74.dp).background(MaterialTheme.colorScheme.surfaceVariant, CircleShape), contentAlignment = Alignment.Center) {
            DropIcon(DropIconKind.Nearby, modifier = Modifier.size(30.dp), tint = MaterialTheme.colorScheme.primary)
        }
    }
}
