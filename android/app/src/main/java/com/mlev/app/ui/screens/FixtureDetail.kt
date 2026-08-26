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
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
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
                val typed = prices[side.key(fixture.id)].orEmpty()
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
                            val typed = prices[side.key(fixture.id)].orEmpty()
                            val opposing = market.sides.firstOrNull { it != side }
                                ?.let { prices[it.key(fixture.id)] }
                            SideRow(
                                side = side,
                                typed = typed,
                                comparison = comparisonFor(side, typed, opposing, oddsFormat, stake),
                                oddsFormat = oddsFormat,
                                onChange = { onPriceChange(side, it) },
                            )
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
            OutlinedTextField(
                value = typed,
                onValueChange = onChange,
                singleLine = true,
                placeholder = { Text(if (oddsFormat == OddsFormat.AMERICAN) "-110" else "1.91") },
                keyboardOptions = KeyboardOptions(
                    // A minus sign is needed for American odds, so this is the
                    // full numeric keyboard rather than a digits-only one.
                    keyboardType = KeyboardType.Number,
                    imeAction = ImeAction.Done,
                ),
                textStyle = MaterialTheme.typography.bodyMedium.copy(
                    fontFamily = FontFamily.Monospace, textAlign = TextAlign.Center,
                ),
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
