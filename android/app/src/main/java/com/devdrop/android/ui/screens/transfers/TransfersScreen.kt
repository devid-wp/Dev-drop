package com.devdrop.android.ui.screens.transfers

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.devdrop.android.ui.components.EmptyState
import com.devdrop.android.ui.components.DropIcon
import com.devdrop.android.ui.components.DropIconKind
import com.devdrop.android.ui.components.ScreenHeader

@Composable
fun TransfersScreen() {
    Column(Modifier.fillMaxSize().padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(22.dp)) {
        ScreenHeader("Transfers", "Your active and recent file activity")
        Surface(Modifier.weight(1f).fillMaxWidth(), color = MaterialTheme.colorScheme.surface,
            shape = RoundedCornerShape(26.dp)) {
            EmptyState(
                title = "No transfers yet",
                message = "When you connect to a server and send or receive a file, it will appear here.",
                modifier = Modifier.padding(28.dp),
                illustration = {
                    DropIcon(DropIconKind.Transfers, modifier = Modifier.padding(bottom = 18.dp),
                        tint = androidx.compose.material3.MaterialTheme.colorScheme.primary)
                },
            )
        }
    }
}
