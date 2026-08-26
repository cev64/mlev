package com.mlev.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
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
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
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
    val focusManager = LocalFocusManager.current
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
            // Not keyed on settings.stake. Re-keying on the saved value
            // rebuilt the field's text mid-word: typing "12.50" got as far as
            // "12.5", which DataStore echoed back a moment later as 12,
            // erasing the decimal the user was in the middle of.
            //
            // `seenStake` is the last stake the store showed, `sentStake` the
            // last one this field saved. A stored value that is either of
            // those is this field's own edit coming back and must not
            // overwrite it — see PriceField in FixtureDetail.kt, which
            // reconciles the same way against Room.
            var stakeText by rememberSaveable { mutableStateOf(formatStake(settings.stake)) }
            var seenStake by rememberSaveable { mutableStateOf(settings.stake) }
            var sentStake by rememberSaveable { mutableStateOf(settings.stake) }
            if (settings.stake != seenStake) {
                seenStake = settings.stake
                if (settings.stake != sentStake && stakeText.toDoubleOrNull() != settings.stake) {
                    stakeText = formatStake(settings.stake)
                }
            }
            val stakeValue = stakeText.toDoubleOrNull()
            val stakeInvalid = stakeText.isNotBlank() && (stakeValue == null || stakeValue < MIN_STAKE)
            OutlinedTextField(
                value = stakeText,
                onValueChange = { raw ->
                    val cleaned = cleanAmount(raw)
                    stakeText = cleaned
                    // Only a usable number is saved. The old version pushed
                    // every keystroke through a setter that floors at 1, so a
                    // half-typed "0" came back as 1 and overwrote the field.
                    cleaned.toDoubleOrNull()?.takeIf { it >= MIN_STAKE }?.let {
                        sentStake = it
                        onStake(it)
                    }
                },
                label = { Text("Stake used for expected value") },
                isError = stakeInvalid,
                supportingText = if (stakeInvalid) {
                    { Text("Enter an amount of 1 or more") }
                } else null,
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Decimal,
                    imeAction = ImeAction.Done,
                ),
                keyboardActions = KeyboardActions(onDone = { focusManager.clearFocus() }),
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
        }

        SettingsCard("Predictions") {
            var url by rememberSaveable { mutableStateOf(settings.bundleUrl) }
            var seenUrl by rememberSaveable { mutableStateOf(settings.bundleUrl) }
            var sentUrl by rememberSaveable { mutableStateOf(settings.bundleUrl) }
            if (settings.bundleUrl != seenUrl) {
                seenUrl = settings.bundleUrl
                if (settings.bundleUrl != sentUrl && url.trim() != settings.bundleUrl) {
                    url = settings.bundleUrl
                }
            }
            val saveUrl = {
                sentUrl = url.trim()
                focusManager.clearFocus()
                onBundleUrl(url.trim())
            }
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
                // An address is not prose: autocorrect and a capitalised first
                // letter turn a working URL into one that resolves nowhere.
                keyboardOptions = KeyboardOptions(
                    keyboardType = KeyboardType.Uri,
                    capitalization = KeyboardCapitalization.None,
                    autoCorrectEnabled = false,
                    imeAction = ImeAction.Done,
                ),
                keyboardActions = KeyboardActions(onDone = { saveUrl() }),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 8.dp)) {
                // Saving now refreshes as part of the same action. Firing both
                // separately raced the write: the refresh read the address
                // still in DataStore and fetched from the old one.
                Button(onClick = saveUrl, enabled = url.isNotBlank()) { Text("Save and refresh") }
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

/** Below this a stake is not a stake; SettingsRepository floors it here too. */
private const val MIN_STAKE = 1.0

/** Digits and at most one decimal point — a stake is never negative. */
internal fun cleanAmount(raw: String): String {
    val out = StringBuilder()
    var decimalSeen = false
    for (char in raw) {
        when {
            char.isDigit() -> out.append(char)
            (char == '.' || char == ',') && !decimalSeen -> {
                decimalSeen = true
                out.append('.')
            }
        }
        if (out.length >= 9) break
    }
    return out.toString()
}

/** A whole stake reads as "100", not "100.0"; pence survive when they matter. */
internal fun formatStake(stake: Double): String =
    if (stake == stake.toLong().toDouble()) stake.toLong().toString()
    else "%.2f".format(stake).trimEnd('0').trimEnd('.')

@Composable
private fun SettingsCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            content()
        }
    }
}
