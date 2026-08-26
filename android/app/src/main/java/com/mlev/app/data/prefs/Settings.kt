package com.mlev.app.data.prefs

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.doublePreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import java.io.IOException

val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

enum class ThemeMode { SYSTEM, LIGHT, DARK }
enum class OddsFormat { AMERICAN, DECIMAL }

data class Settings(
    val themeMode: ThemeMode = ThemeMode.SYSTEM,
    val dynamicColor: Boolean = true,
    val oddsFormat: OddsFormat = OddsFormat.AMERICAN,
    val stake: Double = 100.0,
    val bundleUrl: String = DEFAULT_BUNDLE_URL,
    val lastSport: String = "nfl",
) {
    companion object {
        // Overridden in Settings; this is where CI publishes by default.
        const val DEFAULT_BUNDLE_URL = "https://cev64.github.io/mlev"
    }
}

/**
 * Preferences, in DataStore.
 *
 * Keys are never removed or renamed casually — a settings key that disappears is
 * a setting that silently resets on the next update. New settings get a default
 * here rather than a migration.
 */
class SettingsRepository(private val context: Context) {

    private object Keys {
        val THEME = stringPreferencesKey("theme_mode")
        val DYNAMIC = booleanPreferencesKey("dynamic_color")
        val ODDS = stringPreferencesKey("odds_format")
        val STAKE = doublePreferencesKey("stake")
        val URL = stringPreferencesKey("bundle_url")
        val SPORT = stringPreferencesKey("last_sport")
    }

    val settings: Flow<Settings> = context.dataStore.data
        .catch { cause ->
            // A corrupt preferences file must not take the app down with it.
            if (cause is IOException) emit(emptyPreferences()) else throw cause
        }
        .map { prefs ->
            Settings(
                themeMode = prefs[Keys.THEME]?.let { runCatching { ThemeMode.valueOf(it) }.getOrNull() }
                    ?: ThemeMode.SYSTEM,
                dynamicColor = prefs[Keys.DYNAMIC] ?: true,
                oddsFormat = prefs[Keys.ODDS]?.let { runCatching { OddsFormat.valueOf(it) }.getOrNull() }
                    ?: OddsFormat.AMERICAN,
                stake = prefs[Keys.STAKE] ?: 100.0,
                bundleUrl = prefs[Keys.URL] ?: Settings.DEFAULT_BUNDLE_URL,
                lastSport = prefs[Keys.SPORT] ?: "nfl",
            )
        }

    suspend fun setThemeMode(mode: ThemeMode) = edit { it[Keys.THEME] = mode.name }
    suspend fun setDynamicColor(enabled: Boolean) = edit { it[Keys.DYNAMIC] = enabled }
    suspend fun setOddsFormat(format: OddsFormat) = edit { it[Keys.ODDS] = format.name }
    suspend fun setStake(stake: Double) = edit { it[Keys.STAKE] = stake.coerceAtLeast(1.0) }
    suspend fun setBundleUrl(url: String) = edit { it[Keys.URL] = url.trim() }
    suspend fun setLastSport(sport: String) = edit { it[Keys.SPORT] = sport }

    private suspend fun edit(block: (androidx.datastore.preferences.core.MutablePreferences) -> Unit) {
        context.dataStore.edit(block)
    }
}
