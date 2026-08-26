package com.mlev.app

import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.mlev.app.data.remote.BundleDto
import com.mlev.app.data.remote.BundleService
import com.mlev.app.domain.model.BundleInfo
import com.mlev.app.domain.model.Sport
import com.mlev.app.ui.screens.AboutScreen
import com.mlev.app.ui.theme.MlevTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/**
 * The market half of a bundle, as the app receives and reports it.
 *
 * The app used to show only the numbers that flatter the model — beat the base
 * rate, well calibrated — with nothing about the bar a bet actually has to
 * clear. These pin the parts that are easy to quietly drop: that the blend
 * weight and the posted line survive the wire, and that the screen showing the
 * record shows the losing rows too.
 */
@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class MarketBundleTest {

    @get:Rule val compose = createComposeRule()

    private val json = BundleService.DEFAULT_JSON

    private val payload = """
        {
          "schema": 1, "sport": "nfl", "label": "NFL",
          "generated_at": "2026-08-26T13:58:42+00:00",
          "trained_through": "2026-02-08", "training_rows": 2696,
          "kind": "nfl",
          "blend": {"margin": 0.15, "total": 0.2},
          "backtest": {
            "home_win": {"n": 1954, "brier": 0.21113, "baseline_brier": 0.24864,
                         "accuracy": 0.66684, "ece": 0.02404},
            "margin vs line": {"n": 1960, "model_mae": 9.8208, "market_mae": 9.8224},
            "moneyline +EV": {"n": 1098, "roi": -0.02674, "roi_low": -0.11029,
                              "roi_high": 0.05681, "hit_rate": 0.37614}
          },
          "fixtures": [
            {"id": "2026_01_NE_SEA", "home": "SEA", "away": "NE",
             "kickoff": "2026-09-09", "season": 2026, "week": 1,
             "margin": {"mean": 3.5423, "sd": 11.8931},
             "total": {"mean": 47.0936, "sd": 12.8474},
             "market": {"spread": 3.5, "total": 44.5,
                        "home_price": -180.0, "away_price": 150.0}}
          ]
        }
    """.trimIndent()

    @Test fun `the blend weight and the posted line survive the wire`() {
        val dto = json.decodeFromString<BundleDto>(payload)
        assertEquals(0.15, dto.blend?.margin)
        assertEquals(0.2, dto.blend?.total)

        val market = dto.fixtures.single().market
        assertEquals(3.5, market?.spread)
        assertEquals(44.5, market?.total)
        assertEquals(-180.0, market?.homePrice)
        assertEquals(150.0, market?.awayPrice)
    }

    @Test fun `a bundle with no market block still parses`() {
        // Older exports, and any fixture priced before a line exists.
        val bare = payload
            .replace(Regex(""",\s*"market"\s*:\s*\{[^}]*}""", RegexOption.DOT_MATCHES_ALL), "")
            .replace(""""blend": {"margin": 0.15, "total": 0.2},""", "")
        val dto = json.decodeFromString<BundleDto>(bare)
        assertNull(dto.blend)
        assertNull(dto.fixtures.single().market)
        assertEquals(3.5423, dto.fixtures.single().margin?.mean)
    }

    @Test fun `the market metrics reach the backtest map`() {
        val dto = json.decodeFromString<BundleDto>(payload)
        val vsLine = dto.backtest["margin vs line"]!!
        assertTrue("the model should be reported against the line", vsLine.containsKey("market_mae"))
        assertEquals(-0.02674, dto.backtest["moneyline +EV"]!!["roi"])
    }

    @Test fun `the record screen reports the losing rows, not only the winning ones`() {
        val dto = json.decodeFromString<BundleDto>(payload)
        val info = BundleInfo(
            sport = Sport.NFL, schema = dto.schema, generatedAt = dto.generatedAt,
            trainedThrough = dto.trainedThrough, trainingRows = dto.trainingRows,
            fixtureCount = dto.fixtures.size, backtest = dto.backtest,
            modelWeight = dto.blend?.margin,
        )
        compose.setContent { MlevTheme { AboutScreen(info) } }

        // The screen scrolls, so existence is the claim being made here: the
        // row is on the screen at all, rather than quietly left out.
        compose.onNodeWithText("Home win probability").assertExists()
        // The row that says the model does not beat the line.
        compose.onNodeWithText("Winning margin, against the closing line").assertExists()
        // And the one that says following it lost money.
        compose.onNodeWithText("Backing every +EV moneyline").assertExists()

        val negative = compose.onAllNodes(hasText("-2.7%", substring = true))
            .fetchSemanticsNodes().size
        assertTrue("the negative return has to be on screen, not rounded away", negative > 0)
    }

    @Test fun `the screen says how much of a prediction is the model`() {
        val info = BundleInfo(
            sport = Sport.NFL, schema = 1, generatedAt = "2026-08-26T13:58:42+00:00",
            trainedThrough = "2026-02-08", trainingRows = 2696, fixtureCount = 1,
            backtest = mapOf("home_win" to mapOf("brier" to 0.21113)),
            modelWeight = 0.15,
        )
        compose.setContent { MlevTheme { AboutScreen(info) } }
        val shown = compose.onAllNodes(hasText("15% this model", substring = true))
            .fetchSemanticsNodes().size
        assertTrue("the blend should be stated plainly", shown > 0)
    }
}
