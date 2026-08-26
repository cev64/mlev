package com.mlev.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.mlev.app.data.prefs.OddsFormat
import com.mlev.app.domain.math.Odds
import com.mlev.app.domain.model.FixtureMarkets
import com.mlev.app.domain.model.MarketSide
import com.mlev.app.ui.EdgeFilter
import com.mlev.app.ui.components.EvBadge
import com.mlev.app.ui.components.NoteCard
import com.mlev.app.ui.components.NoteTone
import com.mlev.app.ui.components.ProbabilityBar
import com.mlev.app.ui.components.SectionLabel
import com.mlev.app.ui.components.StatLine
import com.mlev.app.ui.theme.EvColors

/**
 * One fixture: every market, both sides, and what a typed price is worth.
 *
 * On the cover screen this is the whole width; unfolded it is the detail pane
 * beside the list. The composable is the same either way — only its width
 * changes — so folding cannot lose the user's place or their half-typed price.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun FixtureDetail(
    entry: FixtureMarkets,
    prices: Map<String, String>,
    filter: EdgeFilter,
    oddsFormat: OddsFormat,
    stake: Double,
    onPriceChange: (MarketSide, String) -> Unit,
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(12.dp),
) {
    val listState = rememberLazyListState()
    val fixture = entry.fixture
    // Which price field the user is in, if any. A filter re-evaluates on every
    // keystroke, so without this a row could stop matching mid-entry, be
    // removed from the list, and take the keyboard and the half-typed price
    // with it. The row being edited stays put until focus leaves it.
    var editingKey by remember { mutableStateOf<String?>(null) }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        state = listState,
        contentPadding = contentPadding,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item(key = "header") {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    Text(fixture.label, style = MaterialTheme.typography.titleLarge)
                    Text(fixture.kickoff, style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                    fixture.context.forEach { (label, value) -> StatLine(label, value) }
                }
            }
        }

        if (fixture.caution != null) {
            item(key = "caution") { NoteCard(fixture.caution, NoteTone.CAUTION) }
        }

        entry.markets.forEach { market ->
            val visible = market.sides.filter { side ->
                val key = side.key(fixture.id)
                if (key == editingKey) return@filter true
                val typed = prices[key].orEmpty()
                when (filter) {
                    EdgeFilter.ALL -> true
                    EdgeFilter.PRICED -> typed.isNotBlank()
                    EdgeFilter.POSITIVE -> {
                        val other = market.sides.firstOrNull { it != side }
                            ?.let { prices[it.key(fixture.id)] }
                        comparisonFor(side, typed, other, oddsFormat, stake)?.isPositive == true
                    }
                }
            }
            if (visible.isEmpty()) return@forEach

            item(key = "market-${market.name}") {
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(horizontal = 14.dp, vertical = 4.dp)) {
                        SectionLabel(
                            market.name,
                            trailing = if (market.pushProbability > 0.001)
                                "push %.1f%%".format(market.pushProbability * 100) else null,
                        )
                        visible.forEach { side ->
                            val sideKey = side.key(fixture.id)
                            val typed = prices[sideKey].orEmpty()
                            val opposing = market.sides.firstOrNull { it != side }
                                ?.let { prices[it.key(fixture.id)] }
                            // Keyed on the side, so a row that appears or
                            // disappears under a filter cannot hand its
                            // half-typed text to whichever row takes its slot.
                            key(sideKey) {
                                SideRow(
                                    side = side,
                                    typed = typed,
                                    comparison = comparisonFor(side, typed, opposing, oddsFormat, stake),
                                    oddsFormat = oddsFormat,
                                    onChange = { onPriceChange(side, it) },
                                    onFocused = { focused ->
                                        editingKey = if (focused) sideKey
                                        else editingKey.takeIf { it != sideKey }
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SideRow(
    side: MarketSide,
    typed: String,
    comparison: Odds.Comparison?,
    oddsFormat: OddsFormat,
    onChange: (String) -> Unit,
    onFocused: (Boolean) -> Unit = {},
) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(
                side.side,
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.weight(1f),
            )
            EvBadge(comparison?.evPerStake)
        }

        Row(
            Modifier.fillMaxWidth().padding(top = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            ProbabilityBar(side.probability, Modifier.weight(1f), label = side.side)
            // The fair price: what a book with no margin would post.
            Text(
                Odds.formatAmerican(Odds.probabilityToAmerican(side.settlingProbability)),
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.width(52.dp),
                textAlign = TextAlign.End,
            )
            PriceField(
                stored = typed,
                oddsFormat = oddsFormat,
                onChange = onChange,
                onFocused = onFocused,
                modifier = Modifier.width(104.dp),
            )
        }

        if (comparison != null) {
            FlowRow(
                Modifier.fillMaxWidth().padding(top = 2.dp),
                horizontalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Metric("edge", "%.1f%%".format(comparison.edge * 100), comparison.edge > 0)
                comparison.noVigEdge?.let {
                    Metric("no-vig", "%.1f%%".format(it * 100), it > 0)
                }
                Metric("EV", "%.1f%%".format(comparison.evFraction * 100), comparison.evFraction > 0)
                if (comparison.kelly > 0) {
                    Metric("Kelly", "%.1f%%".format(comparison.kelly * 100), null)
                }
            }
        }
    }
}

/**
 * The price the user types against a side.
 *
 * Two things this has to get right, both of which the obvious version gets
 * wrong:
 *
 * 1. **The field owns its own text.** The saved price arrives back from Room,
 *    which is at least one suspending hop away from the keystroke that caused
 *    it. Feeding that value straight back into the field means every character
 *    races the write that produced it: type at any speed and characters are
 *    dropped or reordered, and the cursor jumps to the end of whatever text
 *    arrives. Here the field's own state is authoritative while it is being
 *    edited, and the stored value is adopted only when it changes for some
 *    other reason — cleared from Settings, or a different fixture selected.
 * 2. **A minus sign has to be reachable.** American odds are mostly negative,
 *    and Android's plain number keyboard has no minus key at all, so the most
 *    common price in the app could not be typed. The phone keypad has one.
 *    Decimal odds never go negative, so that format keeps the decimal pad.
 */
@Composable
private fun PriceField(
    stored: String,
    oddsFormat: OddsFormat,
    onChange: (String) -> Unit,
    onFocused: (Boolean) -> Unit,
    modifier: Modifier = Modifier,
) {
    val focusManager = LocalFocusManager.current
    var field by remember { mutableStateOf(TextFieldValue(stored, TextRange(stored.length))) }
    // Two separate facts, and conflating them is what broke the field before:
    // `seen` is the last value the store showed us, `sent` the last value we
    // gave it. A change in the store is only worth adopting when it is neither
    // — otherwise it is this field's own edit arriving back, one or several
    // keystrokes late, and adopting it rewinds what has been typed since.
    var seen by remember { mutableStateOf(stored) }
    var sent by remember { mutableStateOf(stored) }
    if (stored != seen) {
        seen = stored
        if (stored != sent && stored != field.text) {
            field = TextFieldValue(stored, TextRange(stored.length))
        }
    }

    OutlinedTextField(
        value = field,
        onValueChange = { candidate ->
            val cleaned = cleanPrice(candidate.text, candidate.selection.start, oddsFormat)
            field = TextFieldValue(cleaned.text, TextRange(cleaned.caret))
            if (cleaned.text != sent) {
                sent = cleaned.text
                onChange(cleaned.text)
            }
        },
        singleLine = true,
        placeholder = { Text(if (oddsFormat == OddsFormat.AMERICAN) "-110" else "1.91") },
        keyboardOptions = KeyboardOptions(
            keyboardType = if (oddsFormat == OddsFormat.AMERICAN) KeyboardType.Phone
            else KeyboardType.Decimal,
            imeAction = ImeAction.Done,
        ),
        // Done dismissed nothing before this: the keyboard stayed up over the
        // numbers the user had just typed it to see.
        keyboardActions = KeyboardActions(onDone = { focusManager.clearFocus() }),
        textStyle = MaterialTheme.typography.bodyMedium.copy(
            fontFamily = FontFamily.Monospace, textAlign = TextAlign.Center,
        ),
        modifier = modifier.onFocusChanged { onFocused(it.isFocused) },
    )
}

internal data class CleanedPrice(val text: String, val caret: Int)

/** How long a price can sensibly be: "-10000" and "1000.00" both fit. */
private const val MAX_PRICE_LENGTH = 7

/**
 * Keep only what can be part of a price, and carry the cursor along with it.
 *
 * The phone keypad offers `+ - . , * # ;` and a hardware or software keyboard
 * can send anything at all. Accepting those characters into the field means
 * showing text that will never parse and silently scoring nothing; dropping
 * them without tracking the cursor sends it to the end of the line mid-word.
 */
internal fun cleanPrice(raw: String, caret: Int, format: OddsFormat): CleanedPrice {
    val out = StringBuilder()
    var newCaret = 0
    var decimalSeen = false
    for ((index, char) in raw.withIndex()) {
        val keep = when {
            char.isDigit() -> true
            // A sign is only a sign in front, and only where prices are signed.
            (char == '-' || char == '+') ->
                out.isEmpty() && format == OddsFormat.AMERICAN
            // Some locales' keypads send a comma for the decimal separator.
            (char == '.' || char == ',') && !decimalSeen && format == OddsFormat.DECIMAL -> {
                decimalSeen = true
                true
            }
            else -> false
        }
        if (keep && out.length < MAX_PRICE_LENGTH) {
            out.append(if (char == ',') '.' else char)
        }
        if (index < caret) newCaret = out.length
    }
    return CleanedPrice(out.toString(), newCaret.coerceIn(0, out.length))
}

@Composable
private fun Metric(label: String, value: String, positive: Boolean?) {
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(label, style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(
            value,
            style = MaterialTheme.typography.labelSmall,
            fontFamily = FontFamily.Monospace,
            color = when (positive) {
                true -> EvColors.positive()
                false -> EvColors.negative()
                null -> MaterialTheme.colorScheme.onSurface
            },
        )
    }
}

/** Shared by the row and the filter so both agree on what counts as +EV. */
internal fun comparisonFor(
    side: MarketSide,
    typed: String,
    opposing: String?,
    format: OddsFormat,
    stake: Double,
): Odds.Comparison? {
    val odds = typed.trim().toDoubleOrNull() ?: return null
    return runCatching {
        Odds.compare(
            probability = side.probability,
            bookOdds = odds,
            format = if (format == OddsFormat.AMERICAN) Odds.Format.AMERICAN else Odds.Format.DECIMAL,
            pushProbability = side.pushProbability,
            opposingOdds = opposing?.trim()?.toDoubleOrNull(),
            stake = stake,
        )
    }.getOrNull()
}
