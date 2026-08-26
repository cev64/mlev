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
    // EPL
    val grid: List<List<Double>>? = null,
    @SerialName("replacement_rating") val replacementRating: Boolean = false,
)

@Serializable
data class MomentsDto(val mean: Double, val sd: Double)

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
