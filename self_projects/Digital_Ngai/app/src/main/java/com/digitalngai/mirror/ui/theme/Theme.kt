package com.digitalngai.mirror.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Purple = Color(0xFF7C4DFF)
private val DarkBg = Color(0xFF1B1B2F)

private val DarkColors = darkColorScheme(
    primary = Purple,
    background = DarkBg,
    surface = Color(0xFF25253F)
)

private val LightColors = lightColorScheme(
    primary = Purple
)

@Composable
fun DigitalNgaiTheme(content: @Composable () -> Unit) {
    val colors = if (isSystemInDarkTheme()) DarkColors else LightColors
    MaterialTheme(colorScheme = colors, content = content)
}
