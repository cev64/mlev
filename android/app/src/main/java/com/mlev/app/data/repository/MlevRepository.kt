package com.mlev.app.data.repository

import android.content.Context
import com.mlev.app.data.local.BundleEntity
import com.mlev.app.data.local.MlevDatabase
import com.mlev.app.data.local.PriceEntity
import com.mlev.app.data.remote.BundleDto
import com.mlev.app.data.remote.BundleService
import com.mlev.app.domain.markets.MarketBuilder
import com.mlev.app.domain.math.LatticeShape
import com.mlev.app.domain.math.ScorelineDistribution
import com.mlev.app.domain.model.BundleInfo
import com.mlev.app.domain.model.Fixture
import com.mlev.app.domain.model.FixtureMarkets
import com.mlev.app.domain.model.Sport
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.json.Json

/**
 * The single source of truth the UI reads from.
 *
 * Local-first: the screens always render whatever bundle is in Room, and a
 * refresh replaces it only on success. A failed download leaves the last good
 * numbers in place rather than emptying the screen, because stale predictions
 * are far more useful than none when you are standing in front of a betting slip.
 */
class MlevRepository(
    private val database: MlevDatabase,
    private val service: BundleService = BundleService(),
    private val json: Json = BundleService.DEFAULT_JSON,
) {

    fun observeBundle(sport: Sport): Flow<BundleInfo?> =
        database.bundles().observe(sport.key).map { it?.toInfo() }

    fun observePrices(sport: Sport): Flow<Map<String, String>> =
        database.prices().observe(sport.key).map { rows -> rows.associate { it.key to it.odds } }

    fun observeAllPrices(): Flow<List<PriceEntity>> = database.prices().observeAll()

    /**
     * Fixtures with their markets, rebuilt from the stored distribution
     * parameters. This is the computation that makes the phone independent.
     */
    fun observeFixtures(sport: Sport): Flow<List<FixtureMarkets>> =
        database.bundles().observe(sport.key).map { entity ->
            entity ?: return@map emptyList()
            runCatching { buildFixtures(sport, json.decodeFromString(entity.payload)) }
                .getOrElse { emptyList() }
        }

    suspend fun cachedBundle(sport: Sport): BundleDto? =
        database.bundles().get(sport.key)?.let {
            runCatching { json.decodeFromString<BundleDto>(it.payload) }.getOrNull()
        }

    /** Download and store a bundle. Returns null on success, a message on failure. */
    suspend fun refresh(sport: Sport, baseUrl: String): String? =
        when (val result = service.fetchBundle(baseUrl, sport.key)) {
            is BundleService.Result.Success -> {
                val dto = result.value
                database.bundles().upsert(
                    BundleEntity(
                        sport = sport.key,
                        schema = dto.schema,
                        generatedAt = dto.generatedAt,
                        trainedThrough = dto.trainedThrough,
                        trainingRows = dto.trainingRows,
                        fixtureCount = dto.fixtures.size,
                        payload = json.encodeToString(BundleDto.serializer(), dto),
                        downloadedAt = System.currentTimeMillis(),
                    )
                )
                null
            }
            // A sport with nothing published is not a broken setup, and saying
            // so stops the message sending people to change an address that
            // works. EPL fixtures are exported only once the schedule feed
            // lists them, which it does a few days out, so an empty spell
            // between matchdays is the normal state and not a fault.
            is BundleService.Result.Failure ->
                if (result.notFound) {
                    "No ${sport.label} predictions are published yet — they are " +
                        "exported once the fixtures are within a few days."
                } else {
                    result.reason
                }
        }

    suspend fun savePrice(sport: Sport, fixtureId: String, market: String, side: String, odds: String) {
        val key = "$fixtureId|$market|$side"
        if (odds.isBlank()) {
            database.prices().deleteByKey(key)
        } else {
            database.prices().upsert(
                PriceEntity(key, fixtureId, sport.key, market, side, odds.trim(), System.currentTimeMillis())
            )
        }
    }

    suspend fun clearPrices(sport: Sport) = database.prices().clearSport(sport.key)

    suspend fun priceCount(): Int = database.prices().count()

    // ---------------------------------------------------------------- build

    private fun buildFixtures(sport: Sport, dto: BundleDto): List<FixtureMarkets> = when (sport) {
        Sport.NFL -> buildNfl(dto)
        Sport.EPL -> buildEpl(dto)
    }

    private fun buildNfl(dto: BundleDto): List<FixtureMarkets> {
        val marginShape = dto.lattice?.margin?.let {
            LatticeShape(it.values.toIntArray(), it.bump.toDoubleArray())
        } ?: LatticeShape.FLAT
        val totalShape = dto.lattice?.total?.let {
            LatticeShape(it.values.toIntArray(), it.bump.toDoubleArray())
        } ?: LatticeShape.FLAT

        return dto.fixtures.mapNotNull { f ->
            val margin = f.margin ?: return@mapNotNull null
            val total = f.total ?: return@mapNotNull null
            val marginDist = runCatching {
                MarketBuilder.marginDistribution(margin.mean, margin.sd, marginShape)
            }.getOrNull() ?: return@mapNotNull null
            val totalDist = runCatching {
                MarketBuilder.marginDistribution(total.mean, total.sd, totalShape)
            }.getOrNull() ?: return@mapNotNull null

            FixtureMarkets(
                fixture = Fixture(
                    id = f.id,
                    sport = Sport.NFL,
                    home = f.home,
                    away = f.away,
                    kickoff = f.kickoff,
                    season = f.season,
                    week = f.week,
                    context = buildMap {
                        put("Projected score", "%s %.1f — %s %.1f".format(
                            f.home, (total.mean + margin.mean) / 2,
                            f.away, (total.mean - margin.mean) / 2))
                        put("Margin", "%+.1f ± %.1f".format(margin.mean, margin.sd))
                        put("Total", "%.1f ± %.1f".format(total.mean, total.sd))
                        // The book's own numbers, beside the model's. Seeing
                        // the two together is the whole story on a fixture:
                        // where they agree there is nothing to bet, and where
                        // they diverge is where the model is making a claim.
                        f.market?.spread?.let {
                            put("Line", "%s %+.1f".format(f.home, it))
                        }
                        f.market?.total?.let { put("Line total", "%.1f".format(it)) }
                    },
                ),
                markets = MarketBuilder.nflMarkets(f.home, f.away, marginDist, totalDist)
                    .map { m -> m.copy(sides = m.sides.filter { it.isTradeable }) }
                    .filter { it.sides.size >= 2 },
            )
        }
    }

    private fun buildEpl(dto: BundleDto): List<FixtureMarkets> =
        dto.fixtures.mapNotNull { f ->
            val grid = f.grid ?: return@mapNotNull null
            val scoreline = runCatching {
                ScorelineDistribution(grid.map { it.toDoubleArray() }.toTypedArray())
            }.getOrNull() ?: return@mapNotNull null
            val (h, _, a) = scoreline.outcomeProbabilities()
            val likely = scoreline.mostLikelyScore()

            FixtureMarkets(
                fixture = Fixture(
                    id = f.id,
                    sport = Sport.EPL,
                    home = f.home,
                    away = f.away,
                    kickoff = f.kickoff,
                    season = f.season,
                    week = null,
                    context = buildMap {
                        put("Expected goals", "%s %.2f — %s %.2f".format(
                            f.home, scoreline.teamGoals(true).mean,
                            f.away, scoreline.teamGoals(false).mean))
                        put("Most likely score",
                            "%d-%d (%.1f%%)".format(likely.first, likely.second, likely.third * 100))
                    },
                    caution = if (f.replacementRating) {
                        "One club has no rating history (newly promoted) — predicted " +
                            "from a replacement-level prior, so treat these with more caution."
                    } else null,
                ),
                markets = MarketBuilder.eplMarkets(f.home, f.away, scoreline)
                    .map { m -> m.copy(sides = m.sides.filter { it.isTradeable }) }
                    .filter { it.sides.size >= 2 },
            )
        }

    private fun BundleEntity.toInfo(): BundleInfo {
        val dto = runCatching { json.decodeFromString<BundleDto>(payload) }.getOrNull()
        return BundleInfo(
            sport = Sport.from(sport),
            schema = schema,
            generatedAt = generatedAt,
            trainedThrough = trainedThrough,
            trainingRows = trainingRows,
            fixtureCount = fixtureCount,
            backtest = dto?.backtest ?: emptyMap(),
            modelWeight = dto?.blend?.margin,
        )
    }

    companion object {
        fun create(context: Context): MlevRepository =
            MlevRepository(MlevDatabase.get(context))
    }
}
