package com.mlev.app.domain.model

/** Which sport a fixture belongs to. */
enum class Sport(val key: String, val label: String) {
    NFL("nfl", "NFL"),
    EPL("epl", "Premier League");

    companion object {
        fun from(key: String): Sport = entries.firstOrNull { it.key == key } ?: NFL
    }
}

/**
 * One bettable side of one market, with the model's price for it.
 *
 * [probability] is the chance this side wins outright. Where the market can
 * push, [pushProbability] is separate and [settlingProbability] is the number
 * that compares against a book's price.
 */
data class MarketSide(
    val group: String,
    val market: String,
    val side: String,
    val probability: Double,
    val pushProbability: Double = 0.0,
) {
    val settlingProbability: Double
        get() = probability / (1.0 - pushProbability).coerceAtLeast(1e-9)

    val isTradeable: Boolean
        get() {
            val live = 1.0 - pushProbability
            if (live <= 1e-3 || !probability.isFinite()) return false
            val settling = probability / live
            return settling > 1e-3 && settling < 1.0 - 1e-3
        }

    /** A stable key for storing a price against this side. */
    fun key(fixtureId: String): String = "$fixtureId|$market|$side"
}

/** A market grouped with both (or all three) of its sides. */
data class Market(
    val group: String,
    val name: String,
    val sides: List<MarketSide>,
) {
    val pushProbability: Double get() = sides.firstOrNull()?.pushProbability ?: 0.0
}

/** One fixture, with everything needed to price it. */
data class Fixture(
    val id: String,
    val sport: Sport,
    val home: String,
    val away: String,
    val kickoff: String,
    val season: Int?,
    val week: Int?,
    /** Short lines of model context — projected score, margin and its spread. */
    val context: Map<String, String> = emptyMap(),
    /** Set when a club has no rating history and rests on a prior. */
    val caution: String? = null,
) {
    val label: String get() = if (sport == Sport.NFL) "$away @ $home" else "$home vs $away"
}

/** A fixture together with its markets. */
data class FixtureMarkets(val fixture: Fixture, val markets: List<Market>)

/** What the app knows about the model behind the numbers. */
data class BundleInfo(
    val sport: Sport,
    val schema: Int,
    val generatedAt: String,
    val trainedThrough: String,
    val trainingRows: Int,
    val fixtureCount: Int,
    /** Out-of-sample metrics per target, so the app can show the evidence. */
    val backtest: Map<String, Map<String, Double>> = emptyMap(),
)

/** A price the user typed against a side. */
data class SavedPrice(
    val key: String,
    val fixtureId: String,
    val sport: Sport,
    val odds: String,
    val updatedAt: Long,
)
