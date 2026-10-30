package com.devdrop.android.ui.navigation

import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind

enum class AppDestination(val route: String, val label: String, val icon: DropIconKind) {
    Nearby("nearby", "Nearby", DropIconKind.Nearby),
    Send("send", "Send", DropIconKind.Send),
    Transfers("transfers", "Transfers", DropIconKind.Transfers),
    Settings("settings", "Settings", DropIconKind.Settings),
}

@Composable
fun AppNavigationBar(currentRoute: String?, onSelect: (AppDestination) -> Unit) {
    NavigationBar {
        AppDestination.entries.forEach { destination ->
            val selected = currentRoute == destination.route
            NavigationBarItem(
                selected = selected,
                onClick = { onSelect(destination) },
                icon = { DropIcon(destination.icon, tint = if (selected) androidx.compose.material3.MaterialTheme.colorScheme.primary else androidx.compose.material3.MaterialTheme.colorScheme.onSurfaceVariant) },
                label = { Text(destination.label) },
                colors = NavigationBarItemDefaults.colors(),
            )
        }
    }
}
