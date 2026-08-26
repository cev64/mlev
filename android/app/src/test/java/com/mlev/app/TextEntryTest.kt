package com.mlev.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.SemanticsNodeInteraction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.mlev.app.data.prefs.OddsFormat
import com.mlev.app.data.prefs.Settings
import com.mlev.app.domain.markets.MarketBuilder
import com.mlev.app.domain.math.LatticeShape
import com.mlev.app.domain.model.Fixture
import com.mlev.app.domain.model.FixtureMarkets
import com.mlev.app.domain.model.MarketSide
import com.mlev.app.domain.model.Sport
import com.mlev.app.ui.EdgeFilter
import com.mlev.app.ui.screens.FixtureDetail
import com.mlev.app.ui.screens.SettingsScreen
import com.mlev.app.ui.screens.cleanAmount
import com.mlev.app.ui.screens.cleanPrice
import com.mlev.app.ui.screens.formatStake
import com.mlev.app.ui.theme.MlevTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/**
 * Typing into the app's text boxes.
 *
 * Every price the user enters makes a round trip: keystroke -> ViewModel ->
 * Room (or DataStore) -> Flow -> back into the field. That round trip is
 * asynchronous, and a field driven directly from the far end of it loses
 * characters, jumps the cursor, or reverts what was typed. None of that shows
 * up in a test that only asks whether the screen renders, which is why these
 * tests type rather than look.
 */
@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class TextEntryTest {

    @get:Rule val compose = createComposeRule()

    private fun fixture(): FixtureMarkets {
        val shape = LatticeShape(IntArray(101) { it - 50 }, DoubleArray(101) { 1.0 })
        val margin = MarketBuilder.marginDistribution(5.2, 11.9, shape)
        val total = MarketBuilder.marginDistribution(51.0, 12.9, shape)
        return FixtureMarkets(
            fixture = Fixture(
                id = "2026_01_NE_SEA", sport = Sport.NFL, home = "SEA", away = "NE",
                kickoff = "2026-09-09", season = 2026, week = 1,
            ),
            markets = MarketBuilder.nflMarkets("SEA", "NE", margin, total),
        )
    }

    /** What the field is actually showing, as opposed to its label. */
    private fun SemanticsNodeInteraction.editableText(): String =
        fetchSemanticsNode().config[SemanticsProperties.EditableText].text

    private fun field(index: Int = 0) = compose.onAllNodes(hasSetTextAction())[index]

    /**
     * The regression this file exists for: the field used to be driven straight
     * from the stored price, so until Room had written and re-emitted the value
     * the box showed nothing. Here the store never answers at all — the harshest
     * version of the same lag — and the field must still hold what was typed.
     */
    @Test fun `a price survives a store that has not answered yet`() {
        val entered = mutableListOf<String>()
        compose.setContent {
            MlevTheme {
                FixtureDetail(
                    entry = fixture(),
                    prices = emptyMap(),          // never updates, however long we wait
                    filter = EdgeFilter.ALL,
                    oddsFormat = OddsFormat.AMERICAN,
                    stake = 100.0,
                    onPriceChange = { _, odds -> entered += odds },
                )
            }
        }

        val price = field()
        "-110".forEach { price.performTextInput(it.toString()) }
        compose.waitForIdle()

        assertEquals("-110", price.editableText())
        assertEquals("-110", entered.last())
    }

    /** American odds are mostly negative; the minus has to make it through. */
    @Test fun `a negative price reaches the caller intact`() {
        var last: Pair<MarketSide, String>? = null
        compose.setContent {
            MlevTheme {
                FixtureDetail(
                    entry = fixture(), prices = emptyMap(), filter = EdgeFilter.ALL,
                    oddsFormat = OddsFormat.AMERICAN, stake = 100.0,
                    onPriceChange = { side, odds -> last = side to odds },
                )
            }
        }
        field().performTextInput("-137")
        compose.waitForIdle()
        assertEquals("-137", last?.second)
        assertEquals(-137.0, last?.second?.toDoubleOrNull())
    }

    /** A keypad offers `* # ,` and a hardware keyboard offers everything. */
    @Test fun `stray characters never become part of a price`() {
        compose.setContent {
            MlevTheme {
                FixtureDetail(
                    entry = fixture(), prices = emptyMap(), filter = EdgeFilter.ALL,
                    oddsFormat = OddsFormat.AMERICAN, stake = 100.0,
                    onPriceChange = { _, _ -> },
                )
            }
        }
        val price = field()
        price.performTextInput("-1a1#0")
        compose.waitForIdle()
        assertEquals("-110", price.editableText())
    }

    /**
     * The row being typed into used to be filtered out from under the keyboard:
     * "priced only" re-runs on every keystroke, so clearing a box to retype it
     * deleted the row the cursor was in, taking the keyboard with it.
     */
    @Test fun `the row being edited stays on screen under a filter`() {
        val entry = fixture()
        val side = entry.markets.first().sides.first()
        var prices by mutableStateOf(mapOf(side.key(entry.fixture.id) to "-110"))
        compose.setContent {
            MlevTheme {
                FixtureDetail(
                    entry = entry, prices = prices, filter = EdgeFilter.PRICED,
                    oddsFormat = OddsFormat.AMERICAN, stake = 100.0,
                    onPriceChange = { s, odds ->
                        prices = if (odds.isBlank()) prices - s.key(entry.fixture.id)
                        else prices + (s.key(entry.fixture.id) to odds)
                    },
                )
            }
        }
        val price = field()
        price.performTextClearance()
        compose.waitForIdle()
        // The price is gone from the store, so the filter no longer matches
        // this row — but the cursor is still in it, so it stays and can be
        // retyped.
        assertEquals("", price.editableText())
        price.performTextInput("-120")
        compose.waitForIdle()
        assertEquals("-120", prices[side.key(entry.fixture.id)])
    }

    /**
     * Stake used to be re-read from storage on every keystroke and rendered
     * through `toInt()`, so a decimal was erased as it was typed: "12.5" became
     * "12" the moment the store answered.
     */
    @Test fun `a decimal stake is not rounded away while it is typed`() {
        var settings by mutableStateOf(Settings(stake = 100.0))
        compose.setContent {
            MlevTheme {
                SettingsScreen(
                    settings = settings, bundle = null, priceCount = 0,
                    onTheme = {}, onDynamic = {}, onOddsFormat = {},
                    // Exactly what SettingsRepository does with the value.
                    onStake = { settings = settings.copy(stake = maxOf(it, 1.0)) },
                    onBundleUrl = {}, onClearPrices = {}, onRefresh = {},
                )
            }
        }

        val stake = field(0)
        stake.performTextClearance()
        "12.50".forEach { stake.performTextInput(it.toString()) }
        compose.waitForIdle()

        assertEquals("12.50", stake.editableText())
        assertEquals(12.5, settings.stake, 1e-9)
    }

    /** An empty box is a box being retyped, not a request to save 1. */
    @Test fun `clearing the stake does not save anything`() {
        var settings by mutableStateOf(Settings(stake = 100.0))
        val saved = mutableListOf<Double>()
        compose.setContent {
            MlevTheme {
                SettingsScreen(
                    settings = settings, bundle = null, priceCount = 0,
                    onTheme = {}, onDynamic = {}, onOddsFormat = {},
                    onStake = { saved += it; settings = settings.copy(stake = maxOf(it, 1.0)) },
                    onBundleUrl = {}, onClearPrices = {}, onRefresh = {},
                )
            }
        }
        field(0).performTextClearance()
        compose.waitForIdle()
        assertTrue("nothing should be saved for an empty box", saved.isEmpty())
        assertEquals("", field(0).editableText())
    }

    /** Saving an address is one action, so it cannot race its own refresh. */
    @Test fun `saving the address hands over exactly what was typed`() {
        var saved: String? = null
        compose.setContent {
            MlevTheme {
                SettingsScreen(
                    settings = Settings(), bundle = null, priceCount = 0,
                    onTheme = {}, onDynamic = {}, onOddsFormat = {}, onStake = {},
                    onBundleUrl = { saved = it }, onClearPrices = {}, onRefresh = {},
                )
            }
        }
        val url = field(1)
        url.performScrollTo()
        url.performTextClearance()
        url.performTextInput("http://192.168.1.10:8733/dist")
        compose.onNodeWithText("Save and refresh").performScrollTo().performClick()
        compose.waitForIdle()
        assertEquals("http://192.168.1.10:8733/dist", saved)
    }

    // --- the pure helpers, where the edge cases are cheap to state ----------

    @Test fun `cleanPrice keeps the cursor where the user left it`() {
        // "-1a0" with the caret after the stray letter: the cursor belongs
        // after the "1", not at the end of the line.
        val cleaned = cleanPrice("-1a0", caret = 3, format = OddsFormat.AMERICAN)
        assertEquals("-10", cleaned.text)
        assertEquals(2, cleaned.caret)
    }

    @Test fun `cleanPrice allows a sign only in front, and only where prices are signed`() {
        assertEquals("-110", cleanPrice("-110", 4, OddsFormat.AMERICAN).text)
        assertEquals("110", cleanPrice("1-10", 4, OddsFormat.AMERICAN).text)
        assertEquals("191", cleanPrice("-191", 4, OddsFormat.DECIMAL).text)
        assertEquals("1.91", cleanPrice("1,91", 4, OddsFormat.DECIMAL).text)
        // Decimal odds have a point; American odds are whole numbers.
        assertEquals("191", cleanPrice("1.91", 4, OddsFormat.AMERICAN).text)
        assertEquals("1.91", cleanPrice("1.9.1", 5, OddsFormat.DECIMAL).text)
    }

    @Test fun `cleanAmount keeps digits and one decimal point`() {
        assertEquals("12.50", cleanAmount("£12.50"))
        assertEquals("12.50", cleanAmount("12,50"))
        assertEquals("1250", cleanAmount("-1250"))
        assertEquals("", cleanAmount("abc"))
    }

    @Test fun `formatStake keeps a round number round`() {
        assertEquals("100", formatStake(100.0))
        assertEquals("12.5", formatStake(12.5))
        assertEquals("1", formatStake(1.0))
    }
}
