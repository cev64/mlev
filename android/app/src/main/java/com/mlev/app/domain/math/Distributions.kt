package com.mlev.app.domain.math

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.floor
import kotlin.math.ln
import kotlin.math.sqrt

/**
 * The distribution arithmetic, ported from the Python pipeline's core/distributions.py.
 *
 * This exists so the phone can price a line the exporter never precomputed. The
 * bundle ships each fixture's distribution *parameters* rather than a fixed list
 * of probabilities, and this turns those parameters back into any market you ask
 * for. It is why the app needs no connection to the machine that trained it.
 *
 * The Python side has tests asserting a client can rebuild its answers from a
 * bundle; DistributionsTest checks this implementation against the same numbers.
 */

/** Standard normal CDF via the error function. Accurate to ~1e-7, which is far
 *  below the precision any betting market cares about. */
internal fun normalCdf(x: Double, mean: Double = 0.0, sd: Double = 1.0): Double {
    if (sd <= 0.0) return if (x < mean) 0.0 else 1.0
    val z = (x - mean) / (sd * sqrt(2.0))
    return 0.5 * (1.0 + erf(z))
}

/** Abramowitz & Stegun 7.1.26 — the standard rational approximation. */
private fun erf(x: Double): Double {
    val sign = if (x < 0) -1.0 else 1.0
    val a = abs(x)
    val t = 1.0 / (1.0 + 0.3275911 * a)
    val y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * exp(-a * a)
    return sign * y
}

/**
 * The key-number structure of a discrete outcome, learned on the Python side.
 *
 * Football margins are not smooth: about 15% of NFL games are decided by exactly
 * 3 points and 8% by exactly 7, because scores are built from 3s and 7s. A normal
 * distribution puts roughly 3% on each and zero on any exact value, so it cannot
 * price the push on a -3 line at all — and on a whole-number spread the push is
 * the biggest single term.
 *
 * `bump` is the ratio of how often a value really occurs to how often a smooth
 * distribution of the same shape would produce it. It travels in the bundle once,
 * not per fixture, because it is a property of the sport rather than of a game.
 */
class LatticeShape(private val values: IntArray, private val bump: DoubleArray) {
    init {
        require(values.size == bump.size) { "lattice values and bumps must be the same length" }
        require(values.isNotEmpty()) { "lattice shape cannot be empty" }
    }

    private val lookup: Map<Int, Double> = values.indices.associate { values[it] to bump[it] }

    /** 1.0 (no adjustment) outside the range the shape was learned over. */
    fun factor(value: Int): Double = lookup[value] ?: 1.0

    companion object {
        val FLAT = LatticeShape(intArrayOf(0), doubleArrayOf(1.0))
    }
}

/** A distribution over an outcome, in the terms a betting market uses. */
interface Predictive {
    val mean: Double
    val sd: Double

    /** P(X > line). On a whole number this excludes the push. */
    fun probOver(line: Double): Double

    /** P(X == line). Zero unless the outcome can land exactly on it. */
    fun probExactly(line: Double): Double

    /** P(X < line). On a whole number this excludes the push. */
    fun probUnder(line: Double): Double = 1.0 - probOver(line) - probExactly(line)

    fun quantile(q: Double): Double
}

/**
 * A discrete distribution over integers: a smooth density positioned by the
 * model, reshaped by the lattice so the mass clumps onto football's real
 * scoring values.
 */
class LatticeDistribution(
    private val mu: Double,
    private val sigma: Double,
    shape: LatticeShape,
) : Predictive {

    private val low: Int
    private val weights: DoubleArray
    private val cumulative: DoubleArray

    init {
        require(mu.isFinite() && sigma.isFinite() && sigma > 0.0) {
            "LatticeDistribution needs a finite mean and a positive sd, got $mu / $sigma"
        }
        // Five standard deviations either side holds everything that matters.
        low = floor(mu - SUPPORT_SDS * sigma).toInt()
        val high = kotlin.math.ceil(mu + SUPPORT_SDS * sigma).toInt()
        val size = high - low + 1

        val raw = DoubleArray(size)
        var total = 0.0
        for (i in 0 until size) {
            val value = low + i
            // Integrate the density across the integer's cell rather than
            // sampling the centre, so the weights are a real probability mass.
            val cell = normalCdf(value + 0.5, mu, sigma) - normalCdf(value - 0.5, mu, sigma)
            val w = cell * shape.factor(value)
            raw[i] = w
            total += w
        }
        require(total > 0.0 && total.isFinite()) { "lattice distribution collapsed to zero mass" }

        weights = DoubleArray(size) { raw[it] / total }
        cumulative = DoubleArray(size)
        var running = 0.0
        for (i in 0 until size) { running += weights[i]; cumulative[i] = running }
    }

    override val mean: Double get() = weights.indices.sumOf { (low + it) * weights[it] }

    override val sd: Double get() {
        val m = mean
        return sqrt(weights.indices.sumOf { val d = (low + it) - m; d * d * weights[it] })
    }

    private fun indexOf(value: Int): Int = value - low

    override fun probOver(line: Double): Double {
        // Everything strictly greater than the line.
        val firstAbove = floor(line).toInt() + 1
        val i = indexOf(firstAbove)
        if (i <= 0) return 1.0
        if (i > weights.lastIndex) return 0.0
        return (1.0 - cumulative[i - 1]).coerceIn(0.0, 1.0)
    }

    override fun probExactly(line: Double): Double {
        if (abs(line - Math.round(line)) > 1e-9) return 0.0
        val i = indexOf(Math.round(line).toInt())
        return if (i in weights.indices) weights[i] else 0.0
    }

    override fun quantile(q: Double): Double {
        val target = q.coerceIn(0.0, 1.0)
        for (i in cumulative.indices) if (cumulative[i] >= target) return (low + i).toDouble()
        return (low + weights.lastIndex).toDouble()
    }

    companion object { private const val SUPPORT_SDS = 5.0 }
}

/** A continuous normal, for anything without a lattice structure. */
class NormalDistribution(private val mu: Double, private val sigma: Double) : Predictive {
    init { require(mu.isFinite() && sigma > 0.0) { "Normal needs a finite mean and positive sd" } }
    override val mean: Double get() = mu
    override val sd: Double get() = sigma
    override fun probOver(line: Double) = 1.0 - normalCdf(line, mu, sigma)
    override fun probExactly(line: Double) = 0.0
    override fun quantile(q: Double): Double {
        // Bisection: called rarely, and it avoids an inverse-erf approximation.
        var lo = mu - 10 * sigma
        var hi = mu + 10 * sigma
        repeat(80) {
            val mid = (lo + hi) / 2
            if (normalCdf(mid, mu, sigma) < q) lo = mid else hi = mid
        }
        return (lo + hi) / 2
    }
}

/** A discrete distribution read off a weighted set of values. */
class EmpiricalDistribution(values: DoubleArray, weights: DoubleArray) : Predictive {
    private val v: DoubleArray
    private val w: DoubleArray

    init {
        require(values.size == weights.size && values.isNotEmpty())
        val order = values.indices.sortedBy { values[it] }
        val vs = ArrayList<Double>()
        val ws = ArrayList<Double>()
        for (i in order) {
            if (vs.isNotEmpty() && abs(vs.last() - values[i]) < 1e-9) {
                ws[ws.lastIndex] = ws.last() + weights[i]
            } else {
                vs.add(values[i]); ws.add(weights[i])
            }
        }
        val total = ws.sum()
        require(total > 0.0) { "empirical distribution has no mass" }
        v = vs.toDoubleArray()
        w = DoubleArray(ws.size) { ws[it] / total }
    }

    override val mean: Double get() = v.indices.sumOf { v[it] * w[it] }
    override val sd: Double get() {
        val m = mean
        return sqrt(v.indices.sumOf { val d = v[it] - m; d * d * w[it] })
    }
    override fun probOver(line: Double) = v.indices.filter { v[it] > line + 1e-9 }.sumOf { w[it] }
    override fun probExactly(line: Double) = v.indices.filter { abs(v[it] - line) < 1e-9 }.sumOf { w[it] }
    override fun quantile(q: Double): Double {
        var running = 0.0
        for (i in v.indices) { running += w[i]; if (running >= q) return v[i] }
        return v.last()
    }
}
