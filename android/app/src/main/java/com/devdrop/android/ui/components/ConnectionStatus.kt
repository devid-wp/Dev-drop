package com.devdrop.android.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.unit.dp

@Composable
fun ConnectionStatus(
    label: String,
    connected: Boolean = false,
    modifier: Modifier = Modifier,
) {
    val dot = if (connected) MaterialTheme.colorScheme.secondary else Color(0xFFFFC66D)
    Row(
        modifier = modifier.semantics { contentDescription = "Connection status: $label" },
        horizontalArrangement = Arrangement.spacedBy(9.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        androidx.compose.foundation.layout.Box(
            Modifier.size(8.dp).background(dot, CircleShape),
        )
        Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Preview(showBackground = true, backgroundColor = 0xFF090A0F)
@Composable
private fun ConnectionStatusPreview() {
    androidx.compose.material3.MaterialTheme { ConnectionStatus("Server not connected") }
}
