package com.devdrop.android.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.dp

enum class DropIconKind { Nearby, Send, Transfers, Settings, Computer, Search, Files, Photos, Remove, Security, Storage, Info }

@Composable
fun DropIcon(kind: DropIconKind, modifier: Modifier = Modifier, tint: Color = Color.White) {
    Canvas(modifier.size(24.dp)) {
        val scale = size.minDimension / 24f
        fun p(value: Float) = value * scale
        fun line(x1: Float, y1: Float, x2: Float, y2: Float, width: Float = 1.8f) = drawLine(
            tint, Offset(p(x1), p(y1)), Offset(p(x2), p(y2)), strokeWidth = p(width), cap = StrokeCap.Round,
        )
        when (kind) {
            DropIconKind.Nearby -> {
                drawArc(tint, 215f, 110f, false, Offset(p(3f), p(3f)), Size(p(18f), p(18f)), style = Stroke(p(1.8f), cap = StrokeCap.Round))
                drawArc(tint, 215f, 110f, false, Offset(p(7f), p(7f)), Size(p(10f), p(10f)), style = Stroke(p(1.8f), cap = StrokeCap.Round))
                drawCircle(tint, p(1.6f), Offset(p(12f), p(12f)))
            }
            DropIconKind.Send -> { line(12f, 20f, 12f, 4f); line(12f, 4f, 6f, 10f); line(12f, 4f, 18f, 10f); line(5f, 19f, 19f, 19f) }
            DropIconKind.Transfers -> { line(4f, 8f, 19f, 8f); line(19f, 8f, 15f, 4f); line(19f, 8f, 15f, 12f); line(20f, 16f, 5f, 16f); line(5f, 16f, 9f, 12f); line(5f, 16f, 9f, 20f) }
            DropIconKind.Settings -> {
                drawCircle(tint, p(7f), Offset(p(12f), p(12f)), style = Stroke(p(1.8f)))
                drawCircle(tint, p(2.5f), Offset(p(12f), p(12f)))
                for (angle in 0..7) {
                    val rad = angle * Math.PI / 4.0
                    val x1 = 12 + 8 * kotlin.math.cos(rad).toFloat(); val y1 = 12 + 8 * kotlin.math.sin(rad).toFloat()
                    val x2 = 12 + 10 * kotlin.math.cos(rad).toFloat(); val y2 = 12 + 10 * kotlin.math.sin(rad).toFloat()
                    line(x1, y1, x2, y2)
                }
            }
            DropIconKind.Computer -> {
                drawRoundRect(tint, Offset(p(3f), p(4f)), Size(p(18f), p(13f)), androidx.compose.ui.geometry.CornerRadius(p(2f)), style = Stroke(p(1.8f)))
                line(8f, 21f, 16f, 21f); line(12f, 17f, 12f, 21f)
            }
            DropIconKind.Search -> { drawCircle(tint, p(7f), Offset(p(10f), p(10f)), style = Stroke(p(1.8f))); line(15f, 15f, 21f, 21f) }
            DropIconKind.Files -> {
                val path = Path().apply { moveTo(p(6f), p(3f)); lineTo(p(14f), p(3f)); lineTo(p(19f), p(8f)); lineTo(p(19f), p(21f)); lineTo(p(6f), p(21f)); close() }
                drawPath(path, tint, style = Stroke(p(1.8f), cap = StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                line(14f, 3f, 14f, 8f); line(14f, 8f, 19f, 8f)
            }
            DropIconKind.Photos -> {
                drawRoundRect(tint, Offset(p(3f), p(4f)), Size(p(18f), p(16f)), androidx.compose.ui.geometry.CornerRadius(p(3f)), style = Stroke(p(1.8f)))
                drawCircle(tint, p(1.5f), Offset(p(9f), p(9f)))
                drawLine(tint, Offset(p(5f), p(17f)), Offset(p(11f), p(12f)), p(1.8f), cap = StrokeCap.Round)
                drawLine(tint, Offset(p(11f), p(12f)), Offset(p(15f), p(16f)), p(1.8f), cap = StrokeCap.Round)
                drawLine(tint, Offset(p(15f), p(16f)), Offset(p(19f), p(12f)), p(1.8f), cap = StrokeCap.Round)
            }
            DropIconKind.Remove -> { drawCircle(tint, p(9f), center, style = Stroke(p(1.8f))); line(7f, 12f, 17f, 12f) }
            DropIconKind.Security -> {
                val path = Path().apply { moveTo(p(12f), p(3f)); lineTo(p(20f), p(6f)); lineTo(p(19f), p(13f)); lineTo(p(12f), p(21f)); lineTo(p(5f), p(13f)); lineTo(p(4f), p(6f)); close() }
                drawPath(path, tint, style = Stroke(p(1.8f), cap = StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
            }
            DropIconKind.Storage -> { for (y in listOf(5f, 10f, 15f)) { drawRoundRect(tint, Offset(p(4f), p(y)), Size(p(16f), p(4f)), androidx.compose.ui.geometry.CornerRadius(p(1.4f)), style = Stroke(p(1.5f))) } }
            DropIconKind.Info -> { drawCircle(tint, p(9f), center, style = Stroke(p(1.8f))); drawCircle(tint, p(1f), Offset(p(12f), p(8f))); line(12f, 11f, 12f, 16f) }
        }
    }
}
