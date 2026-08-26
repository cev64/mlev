package com.mlev.app.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.mlev.app.data.prefs.ThemeMode

/**
 * The app's own palette, used when dynamic colour is off or unavailable.
 *
 * Deliberately restrained: this is a screen full of numbers, and colour has to
 * mean something here. Green and red are reserved for positive and negative
 * expected value, so nothing else competes with them.
 */
private val BrandPrimary = Color(0xFF2A78D6)
private val BrandPrimaryDark = Color(0xFF3987E5)
private val BrandSecondary = Color(0xFF52514E)

private val LightScheme = lightColorScheme(
    primary = BrandPrimary,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD7E6FB),
    onPrimaryContainer = Color(0xFF0B2B52),
    secondary = BrandSecondary,
    background = Color(0xFFF7F7F5),
    onBackground = Color(0xFF111111),
    surface = Color(0xFFFCFCFB),
    onSurface = Color(0xFF111111),
    surfaceVariant = Color(0xFFEBEBE7),
    onSurfaceVariant = Color(0xFF4A4A47),
    outline = Color(0xFFC8C8C2),
    error = Color(0xFFD03B3B),
)

private val DarkScheme = darkColorScheme(
    primary = BrandPrimaryDark,
    onPrimary = Color(0xFF04203F),
    primaryContainer = Color(0xFF16395F),
    onPrimaryContainer = Color(0xFFD7E6FB),
    secondary = Color(0xFFC3C2B7),
    background = Color(0xFF111110),
    onBackground = Color(0xFFF2F2EE),
    surface = Color(0xFF1A1A19),
    onSurface = Color(0xFFF2F2EE),
    surfaceVariant = Color(0xFF2A2A28),
    onSurfaceVariant = Color(0xFFC3C2B7),
    outline = Color(0xFF4A4A47),
    error = Color(0xFFE07070),
)

/** Reserved for expected value, in both themes. Never reused for anything else. */
object EvColors {
    val positiveLight = Color(0xFF0C7A34)
    val positiveDark = Color(0xFF4BC46B)
    val negativeLight = Color(0xFFC0392B)
    val negativeDark = Color(0xFFE07070)

    @Composable fun positive(): Color =
        if (MaterialTheme.colorScheme.background.luminanceIsDark()) positiveDark else positiveLight

    @Composable fun negative(): Color =
        if (MaterialTheme.colorScheme.background.luminanceIsDark()) negativeDark else negativeLight
}

private fun Color.luminanceIsDark(): Boolean =
    (0.299 * red + 0.587 * green + 0.114 * blue) < 0.5

/**
 * Tabular figures matter more than they sound: a column of probabilities that
 * shifts as digits change is much harder to scan down.
 */
private val AppTypography = Typography().let { base ->
    val mono = TextStyle(fontFamily = FontFamily.Monospace)
    base.copy(
        headlineSmall = base.headlineSmall.copy(fontWeight = FontWeight.SemiBold),
        titleLarge = base.titleLarge.copy(fontWeight = FontWeight.SemiBold),
        titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold),
        labelSmall = base.labelSmall.copy(letterSpacing = 0.6.sp),
        bodySmall = base.bodySmall,
    )
}

@Composable
fun MlevTheme(
    themeMode: ThemeMode = ThemeMode.SYSTEM,
    dynamicColor: Boolean = true,
    content: @Composable () -> Unit,
) {
    val dark = when (themeMode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    val context = LocalContext.current
    val scheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (dark) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)
        dark -> DarkScheme
        else -> LightScheme
    }
    MaterialTheme(colorScheme = scheme, typography = AppTypography, content = content)
}
