package com.devdrop.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val DevDropColors = darkColorScheme(
    primary = Violet,
    onPrimary = Color(0xFF21134C),
    secondary = Mint,
    onSecondary = Color(0xFF06271B),
    background = Ink,
    onBackground = TextPrimary,
    surface = Surface,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceRaised,
    onSurfaceVariant = TextMuted,
    outline = OutlineSoft,
    error = Color(0xFFFF8A91),
)

@Composable
fun DevDropTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = DevDropColors, content = content)
}
