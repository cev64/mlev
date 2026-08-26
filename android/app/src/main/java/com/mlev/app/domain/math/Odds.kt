package com.mlev.app.domain.math

import kotlin.math.abs
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Odds arithmetic — turning a model probability into something comparable to a
 * posted price. Ported from the Python pipeline's core/odds.py.
 *
 * Two traps this is built around:
 *
 * 1. A book's prices do not sum to 100%. The excess is its margin, so comparing
 *    your 55% against an implied 55% is comparing against a number that already
 *    has the house edge in it. [removeVig] strips it.
 * 2. A push is not a loss. An NFL -3 spread lands on exactly 3 about 15% of the
 *    time and returns the stake; treating those as losses misprices the bet by
 *    roughly three to one.
 */
object Odds {

    const val MIN_PROBABILITY = 1e-6

    enum class Format { AMERICAN, DECIMAL }

    fun americanToDecimal(american: Double): Double {
        require(american != 0.0) { "American odds of 0 are not a price" }
        return if (american > 0) 1.0 + american / 100.0 else 1.0 + 100.0 / abs(american)
    }

    fun decimalToAmerican(decimal: Double): Double {
        require(decimal > 1.0) { "decimal odds must exceed 1.0, got $decimal" }
        return if (decimal >= 2.0) ((decimal - 1.0) * 100.0).roundToInt().toDouble()
        else (-100.0 / (decimal - 1.0)).roundToInt().toDouble()
    }

    fun toDecimal(value: Double, format: Format): Double =
        if (format == Format.AMERICAN) americanToDecimal(value) else value

    /** The fair price: 1/p, with no margin added. */
    fun probabilityToDecimal(p: Double): Double {
        require(p > MIN_PROBABILITY && p < 1.0) { "probability must be in (0, 1), got $p" }
        return 1.0 / p
    }

    fun probabilityToAmerican(p: Double): Double = decimalToAmerican(probabilityToDecimal(p))

    fun decimalToProbability(decimal: Double): Double {
        require(decimal > 1.0) { "decimal odds must exceed 1.0, got $decimal" }
        return 1.0 / decimal
    }

    /** "+130" / "-150", the way a book writes it. */
    fun formatAmerican(american: Double): String {
        val value = american.roundToInt()
        return if (value > 0) "+$value" else value.toString()
    }

    /** Strip the book's margin from a complete set of prices on one market. */
    fun removeVig(implied: List<Double>): List<Double> {
        require(implied.size >= 2) { "de-vigging needs every outcome of the market" }
        val total = implied.sum()
        require(total > 0.0) { "implied probabilities sum to zero" }
        return implied.map { it / total }
    }

    /** The book's margin as a fraction. 0.045 is a 4.5% hold. */
    fun overround(implied: List<Double>): Double = implied.sum() - 1.0

    /**
     * P(win | the bet resolves) — the number to compare against a book's price.
     *
     * A book's -110 on a whole-number spread prices the non-push outcomes,
     * because a push returns the stake. Comparing a raw win probability against
     * that implied number compares two different things.
     */
    fun settlingProbability(p: Double, push: Double): Double {
        val live = 1.0 - push
        require(live > MIN_PROBABILITY) { "this market pushes essentially always" }
        return p / live
    }

    /** Expected profit on [stake]. Win keeps the profit, lose loses the stake,
     *  push returns it. */
    fun expectedValue(p: Double, decimal: Double, stake: Double = 100.0, push: Double = 0.0): Double {
        require(p in 0.0..1.0) { "probability must be in [0, 1], got $p" }
        require(push in 0.0..1.0) { "push probability must be in [0, 1], got $push" }
        require(p + push <= 1.0 + 1e-9) { "win + push probability exceeds 1" }
        require(decimal > 1.0) { "decimal odds must exceed 1.0, got $decimal" }
        val lose = 1.0 - p - push
        return p * (decimal - 1.0) * stake - lose * stake
    }

    /**
     * Kelly stake as a fraction of bankroll; zero without an edge.
     *
     * Full Kelly assumes the probability is exactly right, which it never is, so
     * the UI presents this as an upper bound rather than a recommendation.
     */
    fun kelly(p: Double, decimal: Double, push: Double = 0.0, cap: Double = 1.0): Double {
        val b = decimal - 1.0
        require(b > 0.0) { "decimal odds must exceed 1.0, got $decimal" }
        val edge = p * b - (1.0 - p - push)
        return if (edge <= 0.0) 0.0 else min(edge / b, cap)
    }

    /** One side of one market: what the model thinks against what the book pays. */
    data class Comparison(
        val modelProbability: Double,
        val pushProbability: Double,
        val settling: Double,
        val bookDecimal: Double,
        val bookImplied: Double,
        val fairDecimal: Double,
        val fairAmerican: Double,
        val edge: Double,
        val evPerStake: Double,
        val evFraction: Double,
        val kelly: Double,
        val noVigProbability: Double? = null,
        val noVigEdge: Double? = null,
    ) {
        val isPositive: Boolean get() = evFraction > 0.0
    }

    /**
     * @param opposingOdds the other side of the same market. Supplying it adds the
     *   de-vigged comparison, which is the honest one.
     */
    fun compare(
        probability: Double,
        bookOdds: Double,
        format: Format = Format.AMERICAN,
        pushProbability: Double = 0.0,
        opposingOdds: Double? = null,
        stake: Double = 100.0,
    ): Comparison {
        require(probability > MIN_PROBABILITY && probability < 1.0) {
            "model probability must be in (0, 1), got $probability"
        }
        val decimal = toDecimal(bookOdds, format)
        val implied = decimalToProbability(decimal)
        val settling = settlingProbability(probability, pushProbability)

        var noVig: Double? = null
        var noVigEdge: Double? = null
        if (opposingOdds != null) {
            val other = decimalToProbability(toDecimal(opposingOdds, format))
            noVig = removeVig(listOf(implied, other)).first()
            noVigEdge = settling - noVig
        }

        return Comparison(
            modelProbability = probability,
            pushProbability = pushProbability,
            settling = settling,
            bookDecimal = decimal,
            bookImplied = implied,
            fairDecimal = probabilityToDecimal(settling),
            fairAmerican = probabilityToAmerican(settling),
            edge = settling - implied,
            evPerStake = expectedValue(probability, decimal, stake, pushProbability),
            evFraction = expectedValue(probability, decimal, 1.0, pushProbability),
            kelly = kelly(probability, decimal, pushProbability),
            noVigProbability = noVig,
            noVigEdge = noVigEdge,
        )
    }
}
