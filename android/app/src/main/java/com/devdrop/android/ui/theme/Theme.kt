package com.devdrop.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

private val DevDropColors = darkColorScheme(
    primary = Violet,
    onPrimary = Color(0xFF3B0091),
    primaryContainer = VioletDeep,
    onPrimaryContainer = Color(0xFF21005D),
    secondary = TextMuted,
    onSecondary = Color(0xFF332D40),
    tertiary = Mint,
    onTertiary = Color(0xFF00391B),
    background = Ink,
    onBackground = TextPrimary,
    surface = Surface,
    onSurface = TextPrimary,
    surfaceVariant = SurfaceHigh,
    onSurfaceVariant = TextMuted,
    outline = Color(0xFF958EA0),
    outlineVariant = OutlineSoft,
    error = Error,
)

private val DevDropTypography = Typography(
    displaySmall = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 32.sp, lineHeight = 38.sp, letterSpacing = (-0.6).sp),
    headlineMedium = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 26.sp, lineHeight = 32.sp, letterSpacing = (-0.3).sp),
    headlineSmall = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 22.sp, lineHeight = 28.sp),
    titleLarge = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 20.sp, lineHeight = 26.sp),
    titleMedium = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 22.sp),
    bodyLarge = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 16.sp, lineHeight = 24.sp),
    bodyMedium = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 14.sp, lineHeight = 20.sp),
    bodySmall = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.SansSerif, fontSize = 12.sp, lineHeight = 18.sp),
    labelLarge = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 20.sp),
    labelMedium = androidx.compose.ui.text.TextStyle(fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Medium, fontSize = 11.sp, lineHeight = 16.sp),
)

@Composable
fun DevDropTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = DevDropColors, typography = DevDropTypography, content = content)
}
