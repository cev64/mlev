package com.mlev.app.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mlev.app.BuildConfig
import com.mlev.app.domain.model.BundleInfo
import com.mlev.app.ui.components.NoteCard
import com.mlev.app.ui.components.NoteTone
import com.mlev.app.ui.components.StatLine

/**
 * What the numbers are and how far to trust them.
 *
 * The backtest figures ride along in every bundle specifically so this screen
 * can exist. A probability shown without its track record invites more
 * confidence than it has earned.
 */
@Composable
fun AboutScreen(
    bundle: BundleInfo?,
    modifier: Modifier = Modifier,
    contentPadding: PaddingValues = PaddingValues(12.dp),
) {
    Column(
        modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(contentPadding),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        NoteCard(
            "These are one model's opinions, not advice. Check the out-of-sample " +
                "record below before acting on any market: the model beats the base " +
                "rate on NFL moneylines and Premier League match results, and does " +
                "not beat it on Premier League totals or both-teams-to-score.",
            NoteTone.CAUTION,
        )

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("How to read a market", style = MaterialTheme.typography.titleMedium)
                Text(
                    "The percentage is the chance that side wins outright. Where a " +
                        "push is possible it is listed separately — an NFL −3 spread " +
                        "lands on exactly 3 about 15% of the time and returns your " +
                        "stake rather than losing it.\n\n" +
                        "The grey number is the fair price: what a book taking no " +
                        "margin would post. Any real price is worse; the question is " +
                        "by how much.\n\n" +
                        "Type both sides of a market and you also get a no-vig figure. " +
                        "That is the honest comparison — a book's two prices sum to " +
                        "more than 100%, and the excess is its margin.\n\n" +
                        "Kelly is an upper bound on what a bankroll can justify if the " +
                        "model's probability is exactly right. It never is.",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }

        if (bundle != null && bundle.backtest.isNotEmpty()) {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Out-of-sample record", style = MaterialTheme.typography.titleMedium)
                    Text(
                        "Walk-forward validation: trained on every season before the " +
                            "one being predicted, then rolled forward. Nothing the " +
                            "model saw came from the season it was scored on.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    bundle.backtest.forEach { (target, metrics) ->
                        Column(Modifier.padding(top = 6.dp)) {
                            Text(prettyTarget(target), style = MaterialTheme.typography.bodyMedium)
                            metrics["brier"]?.let { brier ->
                                val base = metrics["baseline_brier"]
                                StatLine(
                                    "Brier",
                                    if (base != null) "%.4f vs %.4f guessing".format(brier, base)
                                    else "%.4f".format(brier),
                                )
                            }
                            metrics["mae"]?.let { StatLine("Average error", "%.2f".format(it)) }
                            metrics["accuracy"]?.let { StatLine("Accuracy", "%.1f%%".format(it * 100)) }
                            metrics["ece"]?.let { StatLine("Calibration error", "%.4f".format(it)) }
                            metrics["n"]?.let { StatLine("Sample", "%,d rows".format(it.toInt())) }
                        }
                    }
                }
            }
        }

        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text("This build", style = MaterialTheme.typography.titleMedium)
                StatLine("Version", "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
                StatLine("Application id", BuildConfig.APPLICATION_ID)
                bundle?.let {
                    StatLine("Bundle format", "v${it.schema}")
                    StatLine("Predictions from", it.generatedAt.take(16).replace('T', ' '))
                }
            }
        }
    }
}

private fun prettyTarget(target: String): String = when {
    target == "home_win" -> "Home win probability"
    target == "home_margin" -> "Winning margin"
    target == "total_points" -> "Total points"
    target == "match_outcome_1x2" -> "Match result"
    target == "total_goals" -> "Total goals"
    target.startsWith("spread") -> "Spread ${target.removePrefix("spread")}"
    target.startsWith("outcome_") -> target.removePrefix("outcome_")
        .replaceFirstChar { it.uppercase() }
    else -> target.replace('_', ' ').replaceFirstChar { it.uppercase() }
}
