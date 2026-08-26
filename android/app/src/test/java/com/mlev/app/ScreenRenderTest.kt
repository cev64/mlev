package com.mlev.app

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.assertIsDisplayed
import com.mlev.app.data.prefs.OddsFormat
import com.mlev.app.data.prefs.Settings
import com.mlev.app.data.prefs.ThemeMode
import com.mlev.app.domain.markets.MarketBuilder
import com.mlev.app.domain.math.LatticeShape
import com.mlev.app.domain.math.ScorelineDistribution
import com.mlev.app.domain.model.BundleInfo
import com.mlev.app.domain.model.Fixture
import com.mlev.app.domain.model.FixtureMarkets
import com.mlev.app.domain.model.Sport
import com.mlev.app.ui.EdgeFilter
import com.mlev.app.ui.screens.AboutScreen
import com.mlev.app.ui.screens.FixtureDetail
import com.mlev.app.ui.screens.FixtureList
import com.mlev.app.ui.screens.SettingsScreen
import com.mlev.app.ui.theme.MlevTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import androidx.test.ext.junit.runners.AndroidJUnit4
import kotlin.math.exp

/**
 * Does each screen actually draw?
 *
 * Launching the activity proves `onCreate` survives; it does not prove a screen
 * the user navigates to can compose. A crash in Settings or About would only
 * show up when tapped, which is exactly the kind of thing that reaches a phone
 * unnoticed.
 */
@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class ScreenRenderTest {

    @get:Rule val compose = createComposeRule()

    private fun nflFixture(): FixtureMarkets {
        val shape = LatticeShape(IntArray(101) { it - 50 }, DoubleArray(101) { 1.0 })
        val margin = MarketBuilder.marginDistribution(5.2, 11.9, shape)
        val total = MarketBuilder.marginDistribution(51.0, 12.9, shape)
        return FixtureMarkets(
            fixture = Fixture(
                id = "2026_01_NE_SEA", sport = Sport.NFL, home = "SEA", away = "NE",
                kickoff = "2026-09-09", season = 2026, week = 1,
                context = mapOf("Margin" to "+5.2 ± 11.9"),
            ),
            markets = MarketBuilder.nflMarkets("SEA", "NE", margin, total),
        )
    }

    private fun eplFixture(): FixtureMarkets {
        fun pmf(k: Int, rate: Double): Double {
            var f = 1.0; for (i in 2..k) f *= i
            return exp(-rate) * Math.pow(rate, k.toDouble()) / f
        }
        val grid = Array(9) { h -> DoubleArray(9) { a -> pmf(h, 1.4) * pmf(a, 1.2) } }
        val scoreline = ScorelineDistribution(grid)
        return FixtureMarkets(
            fixture = Fixture(
                id = "epl-1", sport = Sport.EPL, home = "Liverpool", away = "Arsenal",
                kickoff = "2026-08-29", season = 2026, week = null,
                caution = "One club has no rating history.",
            ),
            markets = MarketBuilder.eplMarkets("Liverpool", "Arsenal", scoreline),
        )
    }

    private val bundle = BundleInfo(
        sport = Sport.NFL, schema = 1, generatedAt = "2026-08-26T03:00:00+00:00",
        trainedThrough = "2026-02-08", trainingRows = 2696, fixtureCount = 16,
        backtest = mapOf("home_win" to mapOf("brier" to 0.2225, "baseline_brier" to 0.2486, "n" to 1954.0)),
    )

    @Test fun `fixture list renders`() {
        compose.setContent {
            MlevTheme { FixtureList(listOf(nflFixture()), "2026_01_NE_SEA", emptyMap(), {}) }
        }
        compose.onNodeWithText("NE @ SEA").assertIsDisplayed()
    }

    @Test fun `nfl detail renders every market`() {
        compose.setContent {
            MlevTheme {
                FixtureDetail(nflFixture(), emptyMap(), EdgeFilter.ALL,
                    OddsFormat.AMERICAN, 100.0, { _, _ -> })
            }
        }
        compose.onNodeWithText("NE @ SEA").assertIsDisplayed()
    }

    @Test fun `epl detail renders, including the caution`() {
        compose.setContent {
            MlevTheme {
                FixtureDetail(eplFixture(), emptyMap(), EdgeFilter.ALL,
                    OddsFormat.AMERICAN, 100.0, { _, _ -> })
            }
        }
        compose.onNodeWithText("Liverpool vs Arsenal").assertIsDisplayed()
    }

    @Test fun `settings renders`() {
        compose.setContent {
            MlevTheme {
                SettingsScreen(
                    settings = Settings(), bundle = bundle, priceCount = 3,
                    onTheme = {}, onDynamic = {}, onOddsFormat = {}, onStake = {},
                    onBundleUrl = {}, onClearPrices = {}, onRefresh = {},
                )
            }
        }
        compose.onNodeWithText("Appearance").assertIsDisplayed()
    }

    @Test fun `about renders with the backtest evidence`() {
        compose.setContent { MlevTheme { AboutScreen(bundle) } }
        compose.onNodeWithText("Out-of-sample record").assertIsDisplayed()
    }

    @Test fun `dark theme renders`() {
        compose.setContent {
            MlevTheme(themeMode = ThemeMode.DARK, dynamicColor = false) {
                FixtureList(listOf(nflFixture()), null, emptyMap(), {})
            }
        }
        compose.onNodeWithText("NE @ SEA").assertIsDisplayed()
    }
}
