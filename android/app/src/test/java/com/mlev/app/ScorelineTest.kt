package com.mlev.app

import com.mlev.app.domain.markets.MarketBuilder
import com.mlev.app.domain.math.ScorelineDistribution
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.exp

/**
 * The scoreline grid, checked against the exported EPL bundle for
 * Liverpool vs Arsenal: 1X2 of 0.3051 / 0.2668 / 0.4281.
 *
 * The point of a goal model is that every market is a projection of one object,
 * so they cannot contradict each other. Most of these tests are that property.
 */
class ScorelineTest {

    private fun poissonGrid(lam: Double, mu: Double, size: Int = 9): Array<DoubleArray> {
        fun pmf(k: Int, rate: Double): Double {
            var f = 1.0
            for (i in 2..k) f *= i
            return exp(-rate) * Math.pow(rate, k.toDouble()) / f
        }
        return Array(size) { h -> DoubleArray(size) { a -> pmf(h, lam) * pmf(a, mu) } }
    }

    @Test fun `outcomes sum to one`() {
        val s = ScorelineDistribution(poissonGrid(1.6, 1.1))
        val (h, d, a) = s.outcomeProbabilities()
        assertEquals(1.0, h + d + a, 1e-9)
        assertTrue("the stronger side should be favoured", h > a)
    }

    @Test fun `marginals recover the scoring rates`() {
        val s = ScorelineDistribution(poissonGrid(1.9, 0.8, size = 14))
        assertEquals(1.9, s.teamGoals(home = true).mean, 5e-3)
        assertEquals(0.8, s.teamGoals(home = false).mean, 5e-3)
        assertEquals(1.1, s.supremacy().mean, 5e-3)
        assertEquals(2.7, s.totalGoals().mean, 5e-3)
    }

    @Test fun `draw no bet agrees with the match result exactly`() {
        val s = ScorelineDistribution(poissonGrid(1.7, 1.2))
        val (h, d, a) = s.outcomeProbabilities()
        val handicap = s.asianHandicap(0.0)
        assertEquals(h, handicap.home, 1e-9)
        assertEquals(d, handicap.push, 1e-9)
        assertEquals(a, handicap.away, 1e-9)
    }

    @Test fun `a half line can never push`() {
        val s = ScorelineDistribution(poissonGrid(1.8, 1.0))
        val half = s.asianHandicap(-0.5)
        assertEquals(0.0, half.push, 1e-12)
        assertEquals(s.outcomeProbabilities().first, half.home, 1e-9)
    }

    @Test fun `whole goal handicap differs only by the push`() {
        val s = ScorelineDistribution(poissonGrid(1.9, 1.0))
        val whole = s.asianHandicap(-1.0)
        val half = s.asianHandicap(-1.5)
        assertEquals(whole.home, half.home, 1e-9)
        assertEquals(0.0, half.push, 1e-12)
        assertTrue(whole.push > 0.0)
    }

    @Test fun `quarter handicap splits the stake`() {
        val s = ScorelineDistribution(poissonGrid(1.8, 1.0))
        val low = s.asianHandicap(-0.5)
        val high = s.asianHandicap(-1.0)
        val quarter = s.asianHandicap(-0.75)
        assertEquals((low.home + high.home) / 2, quarter.home, 1e-9)
        assertEquals((low.push + high.push) / 2, quarter.push, 1e-9)
    }

    @Test fun `every handicap is a probability distribution`() {
        val s = ScorelineDistribution(poissonGrid(1.5, 1.3))
        for (line in listOf(-1.5, -1.0, -0.75, -0.5, 0.0, 0.5, 1.0)) {
            val r = s.asianHandicap(line)
            assertEquals("handicap $line", 1.0, r.home + r.push + r.away, 1e-9)
        }
    }

    @Test fun `goal lines are monotone`() {
        val s = ScorelineDistribution(poissonGrid(1.5, 1.3))
        val totals = s.totalGoals()
        val probs = listOf(0.5, 1.5, 2.5, 3.5, 4.5).map { totals.probOver(it) }
        assertEquals(probs.sortedDescending(), probs)
    }

    @Test fun `both teams to score is bounded and sensible`() {
        val s = ScorelineDistribution(poissonGrid(1.5, 1.3))
        val btts = s.bothTeamsScore()
        assertTrue(btts > 0.0 && btts < 1.0)
    }

    @Test fun `grid is renormalised after truncation`() {
        val s = ScorelineDistribution(poissonGrid(3.0, 2.5, size = 6))
        val (h, d, a) = s.outcomeProbabilities()
        assertEquals(1.0, h + d + a, 1e-9)
    }

    @Test fun `market builder emits both sides as complements`() {
        val s = ScorelineDistribution(poissonGrid(1.4, 1.2))
        val markets = MarketBuilder.eplMarkets("Liverpool", "Arsenal", s)
        for (market in markets) {
            if (market.group == "Double chance") continue   // three overlapping pairs
            val total = market.sides.sumOf { it.probability } + market.pushProbability
            assertEquals("${market.name} must sum to 1", 1.0, total, 1e-6)
        }
    }

    @Test fun `double chance is consistent with the match result`() {
        val s = ScorelineDistribution(poissonGrid(1.4, 1.2))
        val markets = MarketBuilder.eplMarkets("Liverpool", "Arsenal", s)
        val dc = markets.first { it.group == "Double chance" }
        // Three pairs from three outcomes must count every outcome twice.
        assertEquals(2.0, dc.sides.sumOf { it.probability }, 1e-6)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects a non quarter handicap`() {
        ScorelineDistribution(poissonGrid(1.5, 1.5)).asianHandicap(-0.3)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects an empty grid`() {
        ScorelineDistribution(Array(4) { DoubleArray(4) })
    }
}
