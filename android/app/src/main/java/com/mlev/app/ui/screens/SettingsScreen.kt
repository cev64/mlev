package com.mlev.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mlev.app.data.prefs.OddsFormat
import com.mlev.app.data.prefs.Settings
import com.mlev.app.data.prefs.ThemeMode
import com.mlev.app.domain.model.BundleInfo

@Composable
fun SettingsScreen(
    settings: Settings,
    bundle: BundleInfo?,
    priceCount: Int,
    onTheme: (ThemeMode) -> Unit,
    onDynamic: (Boolean) -> Unit,
    onOddsFormat: (OddsFormat) -> Unit,
    onStake: (Double) -> Unit,
    onBundleUrl: (String) -> Unit,
    onClearPrices: () -> Unit,
    onRefresh: () -> Unit,
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(12.dp),
) {
    Column(
        modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(contentPadding),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        SettingsCard("Appearance") {
            Text("Theme", style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                ThemeMode.entries.forEach { mode ->
                    FilterChip(
                        selected = settings.themeMode == mode,
                        onClick = { onTheme(mode) },
                        label = { Text(mode.name.lowercase().replaceFirstChar { it.uppercase() }) },
                    )
                }
            }
            Row(
                Modifier.fillMaxWidth().padding(top = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Column(Modifier.weight(1f)) {
                    Text("Match system colours", style = MaterialTheme.typography.bodyMedium)
                    Text(
                        "Uses your wallpaper's palette on Android 12 and later.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Switch(checked = settings.dynamicColor, onCheckedChange = onDynamic)
            }
        }

        SettingsCard("Odds") {
            Text("Format", style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OddsFormat.entries.forEach { format ->
                    FilterChip(
                        selected = settings.oddsFormat == format,
                        onClick = { onOddsFormat(format) },
                        label = { Text(if (format == OddsFormat.AMERICAN) "American (−110)" else "Decimal (1.91)") },
                    )
                }
            }
            var stakeText by rememberSaveable(settings.stake) { mutableStateOf(settings.stake.toInt().toString()) }
            OutlinedTextField(
                value = stakeText,
                onValueChange = {
                    stakeText = it
                    it.toDoubleOrNull()?.let(onStake)
                },
                label = { Text("Stake used for expected value") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }

        SettingsCard("Predictions") {
            var url by rememberSaveable(settings.bundleUrl) { mutableStateOf(settings.bundleUrl) }
            OutlinedTextField(
                value = url,
                onValueChange = { url = it },
                label = { Text("Where predictions are published") },
                supportingText = {
                    Text(
                        "A published URL works anywhere. A computer on your Wi-Fi " +
                            "(http://192.168.x.x:8733/dist) works for testing an export.",
                    )
                },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 8.dp)) {
                Button(onClick = { onBundleUrl(url); onRefresh() }) { Text("Save and refresh") }
                TextButton(onClick = onRefresh) { Text("Refresh now") }
            }
            if (bundle != null) {
                Text(
                    "Last downloaded ${bundle.generatedAt.take(16).replace('T', ' ')} · " +
                        "${bundle.fixtureCount} fixtures · trained through ${bundle.trainedThrough} " +
                        "on ${bundle.trainingRows} games",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
        }

        SettingsCard("Your data") {
            Text(
                "$priceCount saved price${if (priceCount == 1) "" else "s"}. These are stored on " +
                    "this phone and survive app updates.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            var confirming by remember { mutableStateOf(false) }
            if (!confirming) {
                TextButton(onClick = { confirming = true }, modifier = Modifier.padding(top = 4.dp)) {
                    Text("Clear saved prices for this sport")
                }
            } else {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { onClearPrices(); confirming = false }) { Text("Yes, clear them") }
                    TextButton(onClick = { confirming = false }) { Text("Cancel") }
                }
            }
        }
    }
}

@Composable
private fun SettingsCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            content()
        }
    }
}
