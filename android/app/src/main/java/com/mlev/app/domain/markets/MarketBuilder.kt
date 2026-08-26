package com.mlev.app.domain.markets

import com.mlev.app.domain.math.LatticeDistribution
import com.mlev.app.domain.math.LatticeShape
import com.mlev.app.domain.math.Predictive
import com.mlev.app.domain.math.ScorelineDistribution
import com.mlev.app.domain.model.Market
import com.mlev.app.domain.model.MarketSide
import kotlin.math.abs

/**
 * Builds the list of bettable sides for a fixture from its distribution.
 *
 * This is the payoff of shipping parameters rather than probabilities: the lines
 * below are defaults, and [customSpread] / [customTotal] will price anything the
 * user types, including a number nobody precomputed.
 *
 * Both sides of every market are always emitted, and they are complements by
 * construction — the away side is one minus the home side and the push, never a
 * separately computed number that could drift out of agreement.
 */
object MarketBuilder {

    val DEFAULT_SPREADS = doubleArrayOf(-10.5, -7.0, -6.5, -3.5, -3.0, -2.5, 0.0, 2.5, 3.0, 3.5, 6.5, 7.0, 10.5)
    val DEFAULT_TOTALS = doubleArrayOf(37.5, 41.5, 44.0, 44.5, 47.0, 47.5, 51.5)
    val DEFAULT_GOAL_LINES = doubleArrayOf(1.5, 2.5, 3.5, 4.5)
    val DEFAULT_HANDICAPS = doubleArrayOf(-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5)

    fun formatLine(value: Double): String {
        val text = if (value == value.toLong().toDouble()) value.toLong().toString()
        else value.toString().trimEnd('0').trimEnd('.')
        return if (value < 0) text.replace("-", "−") else text
    }

    // ---------------------------------------------------------------- NFL

    fun nflMarkets(
        home: String,
        away: String,
        margin: Predictive,
        total: Predictive,
        spreads: DoubleArray = DEFAULT_SPREADS,
        totals: DoubleArray = DEFAULT_TOTALS,
    ): List<Market> {
        val out = ArrayList<Market>()

        val tie = margin.probExactly(0.0)
        val homeWin = margin.probOver(0.0)
        val awayWin = (1.0 - homeWin - tie).coerceAtLeast(0.0)
        out += Market(
            "Moneyline", "Moneyline",
            listOf(
                MarketSide("Moneyline", "Moneyline", home, homeWin, tie),
                MarketSide("Moneyline", "Moneyline", away, awayWin, tie),
            ),
        )

        for (line in spreads) out += spreadMarket(home, away, margin, line)
        for (line in totals) out += totalMarket(total, line, "Total")
        return out
    }

    fun spreadMarket(home: String, away: String, margin: Predictive, line: Double): Market {
        val cover = margin.probOver(-line)
        val push = margin.probExactly(-line)
        val name = "Spread ${formatLine(line)}"
        return Market(
            "Spread", name,
            listOf(
                MarketSide("Spread", name, "$home ${formatLine(line)}", cover, push),
                MarketSide("Spread", name, "$away ${formatLine(-line)}",
                    (1.0 - cover - push).coerceAtLeast(0.0), push),
            ),
        )
    }

    fun totalMarket(total: Predictive, line: Double, group: String): Market {
        val over = total.probOver(line)
        val push = total.probExactly(line)
        val name = "$group ${formatLine(line)}"
        return Market(
            group, name,
            listOf(
                MarketSide(group, name, "Over ${formatLine(line)}", over, push),
                MarketSide(group, name, "Under ${formatLine(line)}",
                    (1.0 - over - push).coerceAtLeast(0.0), push),
            ),
        )
    }

    // ---------------------------------------------------------------- EPL

    fun eplMarkets(
        home: String,
        away: String,
        scoreline: ScorelineDistribution,
        goalLines: DoubleArray = DEFAULT_GOAL_LINES,
        handicaps: DoubleArray = DEFAULT_HANDICAPS,
    ): List<Market> {
        val out = ArrayList<Market>()
        val (h, d, a) = scoreline.outcomeProbabilities()

        out += Market(
            "Match result", "Match result",
            listOf(
                MarketSide("Match result", "Match result", home, h),
                MarketSide("Match result", "Match result", "Draw", d),
                MarketSide("Match result", "Match result", away, a),
            ),
        )
        out += Market(
            "Double chance", "Double chance",
            listOf(
                MarketSide("Double chance", "Double chance", "$home or Draw", h + d),
                MarketSide("Double chance", "Double chance", "$away or Draw", a + d),
                MarketSide("Double chance", "Double chance", "$home or $away", h + a),
            ),
        )

        for (line in handicaps) out += handicapMarket(home, away, scoreline, line)

        val totals = scoreline.totalGoals()
        for (line in goalLines) out += totalMarket(totals, line, "Goals")

        val btts = scoreline.bothTeamsScore()
        out += Market(
            "Both to score", "Both teams to score",
            listOf(
                MarketSide("Both to score", "Both teams to score", "Yes", btts),
                MarketSide("Both to score", "Both teams to score", "No", 1.0 - btts),
            ),
        )
        return out
    }

    fun handicapMarket(
        home: String, away: String, scoreline: ScorelineDistribution, line: Double,
    ): Market {
        val result = scoreline.asianHandicap(line)
        val name = "Handicap ${formatLine(line)}"
        return Market(
            "Handicap", name,
            listOf(
                MarketSide("Handicap", name, "$home ${formatLine(line)}", result.home, result.push),
                MarketSide("Handicap", name, "$away ${formatLine(-line)}", result.away, result.push),
            ),
        )
    }

    // ------------------------------------------------------------- custom

    /** Price a spread the bundle never precomputed. */
    fun customSpread(home: String, away: String, margin: Predictive, line: Double): Market =
        spreadMarket(home, away, margin, line)

    /** Price a total the bundle never precomputed. */
    fun customTotal(total: Predictive, line: Double, group: String = "Total"): Market =
        totalMarket(total, line, group)

    fun latticeFrom(values: IntArray?, bump: DoubleArray?): LatticeShape =
        if (values == null || bump == null || values.isEmpty()) LatticeShape.FLAT
        else LatticeShape(values, bump)

    fun marginDistribution(mean: Double, sd: Double, shape: LatticeShape): Predictive =
        LatticeDistribution(mean, sd, shape)

    /** Quarter lines are the only sub-half values a handicap can legally take. */
    fun isValidHandicap(line: Double): Boolean = abs(line * 4 - Math.round(line * 4)) < 1e-9
}
