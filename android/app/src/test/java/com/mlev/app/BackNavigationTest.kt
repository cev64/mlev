package com.mlev.app

import android.app.Application
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.lifecycle.SavedStateHandle
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.mlev.app.domain.markets.MarketBuilder
import com.mlev.app.domain.math.LatticeShape
import com.mlev.app.domain.model.Fixture
import com.mlev.app.domain.model.FixtureMarkets
import com.mlev.app.domain.model.Sport
import com.mlev.app.ui.MlevApp
import com.mlev.app.ui.MlevUiState
import com.mlev.app.ui.MlevViewModel
import com.mlev.app.ui.theme.MlevTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/**
 * What the back gesture does.
 *
 * Nothing handled back before this: every press closed the app, including from
 * a fixture detail on a phone, where the detail is a page the user navigated to
 * and back is the obvious way out. The screen was reachable in one tap and
 * escapable only through the bottom bar.
 *
 * A compact width is pinned in the qualifiers, because that is the layout where
 * the detail is a separate page at all.
 */
@RunWith(AndroidJUnit4::class)
@Config(sdk = [34], qualifiers = "w411dp-h891dp")
class BackNavigationTest {

    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

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

    private fun start(state: MlevUiState) {
        val application = ApplicationProvider.getApplicationContext<Application>()
        val viewModel = MlevViewModel(application, SavedStateHandle())
        compose.setContent {
            MlevTheme {
                MlevApp(
                    state = state,
                    priceCount = 0,
                    onSport = {},
                    onSelectFixture = {},
                    onFilter = {},
                    onPrice = { _, _, _ -> },
                    onRefresh = {},
                    onDismissMessage = {},
                    viewModel = viewModel,
                )
            }
        }
    }

    private fun pressBack() {
        compose.runOnUiThread { compose.activity.onBackPressedDispatcher.onBackPressed() }
        compose.waitForIdle()
    }

    /** The filter row rides with the detail pane, so it marks which page is up. */
    private fun onDetail(): Boolean =
        compose.onAllNodes(hasText("Priced")).fetchSemanticsNodes().isNotEmpty()

    @Test fun `back leaves a fixture detail for the list`() {
        val entry = fixture()
        start(MlevUiState(fixtures = listOf(entry), selectedFixtureId = entry.fixture.id, loaded = true))

        compose.onNodeWithText("NE @ SEA").performClick()
        compose.waitForIdle()
        assertTrue("tapping a fixture should open its detail", onDetail())

        pressBack()

        assertTrue("back should return to the list, not close the app", !onDetail())
        assertTrue("the app should still be open", !compose.activity.isFinishing)
        compose.onNodeWithText("NE @ SEA").assertIsDisplayed()
    }

    @Test fun `back leaves settings for the markets`() {
        start(MlevUiState(fixtures = listOf(fixture()), loaded = true))

        compose.onNodeWithText("Settings").performClick()
        compose.waitForIdle()
        compose.onNodeWithText("Appearance").assertIsDisplayed()

        pressBack()

        assertTrue("the app should still be open", !compose.activity.isFinishing)
        compose.onNodeWithText("NE @ SEA").assertIsDisplayed()
    }

    @Test fun `back from the top of the app still closes it`() {
        // The other half of the fix: intercepting back everywhere would trap
        // the user in an app they cannot leave.
        start(MlevUiState(fixtures = listOf(fixture()), loaded = true))

        pressBack()

        assertTrue("back at the top level should close the app", compose.activity.isFinishing)
    }
}
