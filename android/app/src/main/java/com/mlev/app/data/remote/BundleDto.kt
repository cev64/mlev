package com.mlev.app.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * The wire format written by the Python side's core/bundle.py.
 *
 * [schema] is checked before anything is read: an unknown version is refused
 * rather than parsed hopefully, because silently misreading a distribution would
 * produce plausible-looking numbers that are wrong.
 */
@Serializable
data class BundleDto(
    val schema: Int,
    val sport: String,
    val label: String = "",
    @SerialName("generated_at") val generatedAt: String = "",
    @SerialName("trained_through") val trainedThrough: String = "",
    @SerialName("training_rows") val trainingRows: Int = 0,
    val kind: String = "",
    val backtest: Map<String, Map<String, Double>> = emptyMap(),
    val lattice: LatticePairDto? = null,
    /** How far the exported numbers were moved toward the posted line. */
    val blend: BlendDto? = null,
    @SerialName("grid_max_goals") val gridMaxGoals: Int = 0,
    val model: Map<String, Double> = emptyMap(),
    val fixtures: List<FixtureDto> = emptyList(),
)

@Serializable
data class LatticePairDto(
    val margin: LatticeDto? = null,
    val total: LatticeDto? = null,
)

@Serializable
data class LatticeDto(
    val values: List<Int> = emptyList(),
    val bump: List<Double> = emptyList(),
)

@Serializable
data class FixtureDto(
    val id: String,
    val home: String,
    val away: String,
    val kickoff: String = "",
    val season: Int? = null,
    val week: Int? = null,
    // NFL
    val margin: MomentsDto? = null,
    val total: MomentsDto? = null,
    /** What the book had posted when this was exported, where it had. */
    val market: MarketDto? = null,
    // EPL
    val grid: List<List<Double>>? = null,
    @SerialName("replacement_rating") val replacementRating: Boolean = false,
)

@Serializable
data class MomentsDto(val mean: Double, val sd: Double)

/**
 * The weight the pipeline put on the model rather than the market.
 *
 * 0.15 means the exported distribution is 15% this model's own opinion and 85%
 * the posted line. The weight is fitted on training seasons only; it is carried
 * here so the app can say how much of a number is the model's, rather than
 * implying all of it is.
 */
@Serializable
data class BlendDto(
    val margin: Double? = null,
    val total: Double? = null,
)

@Serializable
data class MarketDto(
    val spread: Double? = null,
    val total: Double? = null,
    @SerialName("home_price") val homePrice: Double? = null,
    @SerialName("away_price") val awayPrice: Double? = null,
)

@Serializable
data class IndexDto(
    val schema: Int = 0,
    val bundles: List<IndexEntryDto> = emptyList(),
)

@Serializable
data class IndexEntryDto(
    val sport: String,
    val label: String = "",
    val file: String = "",
    @SerialName("generated_at") val generatedAt: String = "",
    val fixtures: Int = 0,
    val schema: Int = 0,
)
