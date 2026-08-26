package com.mlev.app

import com.mlev.app.domain.math.Odds
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The same cases as the Python suite's tests/test_odds.py, asserted against the
 * same expected numbers. If these two ever disagree, the phone and the pipeline
 * are pricing bets differently, which is exactly the bug worth catching early.
 */
class OddsTest {

    @Test fun `american and decimal round trip`() {
        for (american in listOf(-350.0, -150.0, -110.0, 100.0, 130.0, 250.0, 900.0)) {
            assertEquals(american, Odds.decimalToAmerican(Odds.americanToDecimal(american)), 1e-6)
        }
    }

    @Test fun `known american conversions`() {
        assertEquals(1.909091, Odds.americanToDecimal(-110.0), 1e-5)
        assertEquals(2.0, Odds.americanToDecimal(100.0), 1e-9)
        assertEquals(1.5, Odds.americanToDecimal(-200.0), 1e-9)
    }

    @Test fun `even money is plus 100`() {
        assertEquals("+100", Odds.formatAmerican(Odds.probabilityToAmerican(0.5)))
    }

    @Test fun `minus 110 implies the famous 52 38`() {
        assertEquals(0.5238, Odds.decimalToProbability(Odds.americanToDecimal(-110.0)), 1e-4)
    }

    @Test fun `standard two way hold is about four and a half percent`() {
        val implied = List(2) { Odds.decimalToProbability(Odds.americanToDecimal(-110.0)) }
        assertEquals(0.0476, Odds.overround(implied), 1e-4)
        val fair = Odds.removeVig(implied)
        assertEquals(1.0, fair.sum(), 1e-9)
        assertEquals(0.5, fair[0], 1e-9)
    }

    @Test fun `break even price has zero ev`() {
        assertEquals(0.0, Odds.expectedValue(0.5238, Odds.americanToDecimal(-110.0)), 0.02)
    }

    @Test fun `ev scales with stake`() {
        val d = Odds.americanToDecimal(150.0)
        assertEquals(25.0, Odds.expectedValue(0.5, d, 100.0), 1e-9)
        assertEquals(12.5, Odds.expectedValue(0.5, d, 50.0), 1e-9)
    }

    @Test fun `pushes are returned not lost`() {
        val d = Odds.americanToDecimal(-110.0)
        val asLoss = Odds.expectedValue(0.46, d, 100.0, 0.0)
        val properly = Odds.expectedValue(0.46, d, 100.0, 0.08)
        assertTrue("a push must beat treating it as a loss", properly > asLoss)
        assertEquals(0.46 * 90.909 - 46.0, properly, 0.05)
    }

    @Test fun `settling probability is the comparable number`() {
        assertEquals(0.5, Odds.settlingProbability(0.46, 0.08), 1e-9)
        assertEquals(0.5, Odds.settlingProbability(0.5, 0.0), 1e-9)
    }

    @Test fun `kelly is zero without an edge`() {
        val d = Odds.americanToDecimal(-110.0)
        assertEquals(0.0, Odds.kelly(0.50, d), 1e-9)
        assertTrue(Odds.kelly(0.60, d) > 0.0)
        assertEquals(0.20, Odds.kelly(0.6, 2.0), 1e-9)   // closed form: 2p - 1
    }

    @Test fun `compare reports a real edge`() {
        val c = Odds.compare(0.58, -110.0, opposingOdds = -110.0)
        assertTrue(c.isPositive)
        assertEquals(0.58 - 0.5238, c.edge, 1e-3)
        assertEquals(0.5, c.noVigProbability!!, 1e-9)
        assertEquals(0.08, c.noVigEdge!!, 1e-3)
        assertEquals(10.73, c.evPerStake, 0.05)
        assertEquals("-138", Odds.formatAmerican(c.fairAmerican))
    }

    @Test fun `compare uses the settling probability against the book`() {
        val c = Odds.compare(0.46, -110.0, pushProbability = 0.08, opposingOdds = -110.0)
        assertEquals(0.5, c.noVigProbability!!, 1e-9)
        assertEquals(0.0, c.noVigEdge!!, 1e-9)
        assertEquals("+100", Odds.formatAmerican(c.fairAmerican))
    }

    @Test fun `compare flags a bad price`() {
        val c = Odds.compare(0.45, -150.0)
        assertTrue(!c.isPositive)
        assertEquals(0.0, c.kelly, 1e-9)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `zero american odds are rejected`() { Odds.americanToDecimal(0.0) }

    @Test(expected = IllegalArgumentException::class)
    fun `devigging needs the whole market`() { Odds.removeVig(listOf(0.55)) }

    @Test(expected = IllegalArgumentException::class)
    fun `push cannot exceed what is left`() { Odds.expectedValue(0.7, 2.0, 100.0, 0.5) }
}
