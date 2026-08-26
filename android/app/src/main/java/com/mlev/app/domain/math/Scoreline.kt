package com.mlev.app.domain.math

import kotlin.math.abs
import kotlin.math.round

/**
 * A joint distribution over (home goals, away goals).
 *
 * Every soccer market is a projection of this one object: the match result, any
 * handicap, any goal line, both-teams-to-score, correct score. Deriving them all
 * from the same grid is what makes them mutually consistent — model the markets
 * separately and you can end up quoting a match result that disagrees with your
 * own over/under.
 *
 * The bundle ships the grid per fixture, so the phone can answer a line the
 * exporter never precomputed.
 */
class ScorelineDistribution(grid: Array<DoubleArray>) {

    val grid: Array<DoubleArray>
    val maxGoals: Int

    init {
        require(grid.isNotEmpty() && grid.all { it.size == grid.size }) {
            "scoreline grid must be square (home goals by away goals)"
        }
        val total = grid.sumOf { row -> row.sum() }
        require(total > 0.0 && total.isFinite()) { "scoreline grid has no probability mass" }
        // It arrives truncated at max goals, so it is a hair short of 1.
        this.grid = Array(grid.size) { r -> DoubleArray(grid.size) { c -> grid[r][c] / total } }
        maxGoals = grid.size - 1
    }

    /** Home win / draw / away win. */
    fun outcomeProbabilities(): Triple<Double, Double, Double> {
        var home = 0.0; var draw = 0.0; var away = 0.0
        for (h in grid.indices) for (a in grid.indices) {
            val p = grid[h][a]
            when {
                h > a -> home += p
                h == a -> draw += p
                else -> away += p
            }
        }
        return Triple(home, draw, away)
    }

    /** Distribution of (home goals - away goals) — the handicap market. */
    fun supremacy(): Predictive = collapse { h, a -> (h - a).toDouble() }

    /** Distribution of total goals — the over/under market. */
    fun totalGoals(): Predictive = collapse { h, a -> (h + a).toDouble() }

    /** One side's goals — team totals. */
    fun teamGoals(home: Boolean): Predictive = collapse { h, a -> (if (home) h else a).toDouble() }

    private inline fun collapse(f: (Int, Int) -> Double): Predictive {
        val values = ArrayList<Double>(grid.size * grid.size)
        val weights = ArrayList<Double>(grid.size * grid.size)
        for (h in grid.indices) for (a in grid.indices) {
            values.add(f(h, a)); weights.add(grid[h][a])
        }
        return EmpiricalDistribution(values.toDoubleArray(), weights.toDoubleArray())
    }

    /** P(both teams score). */
    fun bothTeamsScore(): Double {
        var total = 0.0
        for (h in 1 until grid.size) for (a in 1 until grid.size) total += grid[h][a]
        return total
    }

    /** The single most likely scoreline, and how likely it is. */
    fun mostLikelyScore(): Triple<Int, Int, Double> {
        var best = Triple(0, 0, -1.0)
        for (h in grid.indices) for (a in grid.indices) {
            if (grid[h][a] > best.third) best = Triple(h, a, grid[h][a])
        }
        return best
    }

    /**
     * Asian handicap, applied to the home side: -1.5 means home must win by two.
     *
     * A quarter line splits the stake across the two adjacent half-lines, which
     * is what the market actually does with it.
     */
    fun asianHandicap(line: Double): HandicapResult {
        require(abs(line * 4 - round(line * 4)) < 1e-9) { "handicap $line is not a quarter-line" }
        if (abs(line * 2 - round(line * 2)) > 1e-9) {
            val a = asianHandicap(line - 0.25)
            val b = asianHandicap(line + 0.25)
            return HandicapResult((a.home + b.home) / 2, (a.push + b.push) / 2, (a.away + b.away) / 2)
        }
        val sup = supremacy()
        return HandicapResult(
            home = sup.probOver(-line),
            push = sup.probExactly(-line),
            away = sup.probUnder(-line),
        )
    }

    data class HandicapResult(val home: Double, val push: Double, val away: Double)
}
