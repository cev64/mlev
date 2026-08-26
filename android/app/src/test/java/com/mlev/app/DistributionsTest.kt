package com.mlev.app

import com.mlev.app.domain.math.LatticeDistribution
import com.mlev.app.domain.math.LatticeShape
import com.mlev.app.domain.math.NormalDistribution
import com.mlev.app.domain.math.normalCdf
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The lattice, checked against the numbers the Python exporter actually produced
 * for the first fixture of NFL week 1 2026 (SEA vs NE): margin mean 5.2231,
 * sd 11.9147, with the exported bumps at the key numbers.
 *
 * These are the values a real bundle contains, so a regression here means the
 * phone would price a spread differently from the model that trained it.
 */
class DistributionsTest {

    // As exported: bump 2.5978 on +3, 1.441 on +7, 0.1154 on a tie.
    private fun realisticShape(): LatticeShape {
        val values = IntArray(101) { it - 50 }
        val bump = DoubleArray(101) { 1.0 }
        fun set(v: Int, b: Double) { bump[v + 50] = b }
        set(3, 2.5978); set(-3, 2.4375); set(7, 1.441); set(-7, 1.38)
        set(0, 0.1154)
        return LatticeShape(values, bump)
    }

    @Test fun `normal cdf matches known values`() {
        assertEquals(0.5, normalCdf(0.0), 1e-6)
        assertEquals(0.8413447, normalCdf(1.0), 1e-5)
        assertEquals(0.9772499, normalCdf(2.0), 1e-5)
        assertEquals(0.0227501, normalCdf(-2.0), 1e-5)
    }

    @Test fun `lattice preserves the predicted centre and spread`() {
        val d = LatticeDistribution(5.2231, 11.9147, realisticShape())
        assertEquals(5.2231, d.mean, 0.6)
        assertEquals(11.9147, d.sd, 0.9)
    }

    @Test fun `lattice is a proper distribution`() {
        val d = LatticeDistribution(3.0, 12.0, realisticShape())
        for (line in listOf(-7.0, -3.0, 0.0, 3.0, 7.0)) {
            assertEquals(
                "over + push + under must be 1 at $line",
                1.0, d.probOver(line) + d.probExactly(line) + d.probUnder(line), 1e-9,
            )
        }
        val quantiles = listOf(0.1, 0.25, 0.5, 0.75, 0.9).map { d.quantile(it) }
        assertEquals(quantiles.sorted(), quantiles)
    }

    @Test fun `key numbers carry real push probability`() {
        val d = LatticeDistribution(5.2231, 11.9147, realisticShape())
        val normal = NormalDistribution(5.2231, 11.9147)
        val latticePush = d.probExactly(3.0)
        val normalCell = normalCdf(3.5, 5.2231, 11.9147) - normalCdf(2.5, 5.2231, 11.9147)

        assertTrue("a -3 push must be substantial, got $latticePush", latticePush > 0.05)
        assertTrue("the lattice must beat a normal on a key number", latticePush > 2 * normalCell)
        // A continuous distribution cannot express a push at all.
        assertEquals(0.0, normal.probExactly(3.0), 1e-12)
    }

    @Test fun `half point lines never push`() {
        val d = LatticeDistribution(5.2231, 11.9147, realisticShape())
        assertEquals(0.0, d.probExactly(3.5), 1e-12)
        assertEquals(1.0, d.probOver(3.5) + d.probUnder(3.5), 1e-9)
    }

    @Test fun `ties are suppressed the way football actually behaves`() {
        val d = LatticeDistribution(0.5, 12.0, realisticShape())
        // A normal would put ~3% on an exact tie; real NFL ties are ~0.3%.
        assertTrue("tie probability should be small, got ${d.probExactly(0.0)}",
            d.probExactly(0.0) < 0.01)
    }

    @Test fun `can price a line that was never precomputed`() {
        val d = LatticeDistribution(5.2231, 11.9147, realisticShape())
        val at45 = d.probOver(4.5)
        assertTrue(at45 > 0.0 && at45 < 1.0)
        assertTrue("must sit between its neighbours",
            d.probOver(5.5) < at45 && at45 < d.probOver(3.5))
    }

    @Test fun `flat shape reduces to a discretised normal`() {
        val d = LatticeDistribution(0.0, 10.0, LatticeShape.FLAT)
        assertEquals(0.5, d.probOver(0.0) + d.probExactly(0.0) / 2, 0.02)
        assertEquals(0.0, d.mean, 0.05)
        assertEquals(10.0, d.sd, 0.2)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `rejects a zero standard deviation`() {
        LatticeDistribution(0.0, 0.0, LatticeShape.FLAT)
    }
}
