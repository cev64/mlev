package com.mlev.app.widget

import android.content.Context
import android.content.Intent
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.action.actionStartActivity
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.provideContent
import androidx.glance.background
import androidx.glance.layout.Alignment
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.padding
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import com.mlev.app.MainActivity
import com.mlev.app.data.local.MlevDatabase
import com.mlev.app.data.repository.MlevRepository
import com.mlev.app.domain.math.Odds
import com.mlev.app.domain.model.Sport
import com.mlev.app.ui.screens.comparisonFor
import com.mlev.app.data.prefs.OddsFormat
import kotlinx.coroutines.flow.first

/**
 * A home-screen widget showing where the value currently is.
 *
 * It reads the same Room database the app does — no duplicate copy of the
 * user's prices — and only recomputes when Android asks it to, rather than
 * polling. There is nothing to poll for anyway: the numbers change when a new
 * bundle is downloaded or a price is typed, both of which happen in the app.
 *
 * Tapping through deep-links into the app rather than just opening the home
 * screen.
 */
class EdgeWidget : GlanceAppWidget() {

    override val sizeMode = SizeMode.Exact

    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val repository = MlevRepository(MlevDatabase.get(context))
        val rows = topEdges(repository)

        provideContent {
            GlanceTheme {
                WidgetBody(rows)
            }
        }
    }

    /** Best expected value per fixture, across every sport and every side. */
    private suspend fun topEdges(repository: MlevRepository): List<EdgeRow> {
        val out = mutableListOf<EdgeRow>()
        for (sport in Sport.entries) {
            val fixtures = repository.observeFixtures(sport).first()
            val prices = repository.observePrices(sport).first()
            if (fixtures.isEmpty() || prices.isEmpty()) continue

            for (entry in fixtures) {
                var best: Pair<String, Odds.Comparison>? = null
                for (market in entry.markets) {
                    for (side in market.sides) {
                        val typed = prices[side.key(entry.fixture.id)].orEmpty()
                        if (typed.isBlank()) continue
                        val opposing = market.sides.firstOrNull { it != side }
                            ?.let { prices[it.key(entry.fixture.id)] }
                        val comparison = comparisonFor(
                            side, typed, opposing, OddsFormat.AMERICAN, 100.0,
                        ) ?: continue
                        if (best == null || comparison.evPerStake > best!!.second.evPerStake) {
                            best = side.side to comparison
                        }
                    }
                }
                best?.let { (label, comparison) ->
                    out += EdgeRow(entry.fixture.label, label, comparison.evPerStake)
                }
            }
        }
        return out.sortedByDescending { it.ev }.take(MAX_ROWS)
    }

    data class EdgeRow(val fixture: String, val side: String, val ev: Double)

    companion object { const val MAX_ROWS = 6 }
}

@Composable
private fun WidgetBody(rows: List<EdgeWidget.EdgeRow>) {
    Column(
        modifier = GlanceModifier
            .fillMaxSize()
            .background(GlanceTheme.colors.widgetBackground)
            .padding(12.dp)
            .clickable(actionStartActivity<MainActivity>()),
    ) {
        Text(
            "mlev — best edges",
            style = TextStyle(
                fontWeight = FontWeight.Bold,
                color = GlanceTheme.colors.onSurface,
            ),
        )
        Spacer(GlanceModifier.height(6.dp))

        if (rows.isEmpty()) {
            Text(
                "Type a book's price in the app and the best edges appear here.",
                style = TextStyle(color = GlanceTheme.colors.onSurfaceVariant),
            )
            return@Column
        }

        rows.forEach { row ->
            Row(
                modifier = GlanceModifier.fillMaxWidth().padding(vertical = 3.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(GlanceModifier.defaultWeight()) {
                    Text(
                        row.side,
                        style = TextStyle(
                            color = GlanceTheme.colors.onSurface,
                            fontWeight = FontWeight.Medium,
                        ),
                        maxLines = 1,
                    )
                    Text(
                        row.fixture,
                        style = TextStyle(color = GlanceTheme.colors.onSurfaceVariant),
                        maxLines = 1,
                    )
                }
                Text(
                    "%s%.1f".format(if (row.ev > 0) "+" else "", row.ev),
                    style = TextStyle(
                        fontWeight = FontWeight.Bold,
                        color = if (row.ev > 0) GlanceTheme.colors.primary
                        else GlanceTheme.colors.onSurfaceVariant,
                    ),
                )
            }
        }
    }
}

private fun GlanceModifier.height(dp: androidx.compose.ui.unit.Dp): GlanceModifier =
    this.then(GlanceModifier.padding(top = dp))

/** Registered in the manifest; Android instantiates this, not the widget itself. */
class EdgeWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = EdgeWidget()
}
