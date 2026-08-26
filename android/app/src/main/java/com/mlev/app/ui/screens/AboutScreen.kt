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
            "These are one model's opinions, not advice.\n\n" +
                "What the record below does and does not say: this model beats " +
                "the base rate in every season tested, and now matches the " +
                "closing line. It does not beat the closing line by enough to " +
                "overcome the book's margin — flat-staked, following its own " +
                "+EV picks has lost money out of sample. Treat a big edge as a " +
                "reason to look again, not a reason to bet.",
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
                        "model's probability is exactly right. It never is.\n\n" +
                        "Where a fixture shows a Line, that is what the book had " +
                        "posted when these predictions were built. The model's " +
                        "number is already pulled most of the way toward it, so a " +
                        "remaining gap is the part the model is actually claiming.",
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
                    bundle.modelWeight?.let { weight ->
                        Text(
                            "These predictions are %.0f%% this model and %.0f%% the ".format(
                                weight * 100, (1 - weight) * 100,
                            ) + "posted line. The weight is fitted on past seasons " +
                                "only — the model gets as much say as it has earned " +
                                "against the market, and no more.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                    }
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
                            // The market rows. A model that beats the base rate
                            // and loses to the line is the normal case, and the
                            // screen has to be able to say so.
                            metrics["market_mae"]?.let { market ->
                                val model = metrics["model_mae"]
                                if (model != null) {
                                    StatLine(
                                        "Against the line",
                                        "%.2f model vs %.2f line — %s".format(
                                            model, market,
                                            if (model < market) "model closer" else "line closer",
                                        ),
                                    )
                                }
                            }
                            metrics["roi"]?.let { roi ->
                                val low = metrics["roi_low"]
                                val high = metrics["roi_high"]
                                StatLine(
                                    "Flat-stake return",
                                    if (low != null && high != null) {
                                        "%+.1f%% (95%%: %+.1f%% to %+.1f%%)".format(
                                            roi * 100, low * 100, high * 100,
                                        )
                                    } else "%+.1f%%".format(roi * 100),
                                )
                            }
                            metrics["hit_rate"]?.let { StatLine("Hit rate", "%.1f%%".format(it * 100)) }
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
    target == "margin vs line" -> "Winning margin, against the closing line"
    target == "total vs line" -> "Total points, against the closing line"
    target == "moneyline +EV" -> "Backing every +EV moneyline"
    target == "moneyline EV>10%" -> "Backing only edges over 10%"
    target == "moneyline every side" -> "Backing every side (the house edge)"
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
