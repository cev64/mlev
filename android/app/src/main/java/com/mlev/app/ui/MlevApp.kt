package com.mlev.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.SportsFootball
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationRail
import androidx.compose.material3.NavigationRailItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.VerticalDivider
import androidx.compose.material3.adaptive.currentWindowAdaptiveInfo
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.window.core.layout.WindowWidthSizeClass
import com.mlev.app.domain.model.MarketSide
import com.mlev.app.domain.model.Sport
import com.mlev.app.ui.components.NoteCard
import com.mlev.app.ui.components.NoteTone
import com.mlev.app.ui.screens.AboutScreen
import com.mlev.app.ui.screens.FixtureDetail
import com.mlev.app.ui.screens.FixtureList
import com.mlev.app.ui.screens.SettingsScreen
import com.mlev.app.ui.screens.comparisonFor

enum class Destination(val label: String) { MARKETS("Markets"), SETTINGS("Settings"), ABOUT("About") }

/**
 * The app shell.
 *
 * Layout is decided by the available window width, never by the device model, so
 * it does the right thing in split screen and a resized window as well as folded
 * and unfolded:
 *
 *  - Compact  (a folded cover screen, or a narrow split-screen pane) — bottom
 *    navigation, one pane at a time, list replaced by detail on tap.
 *  - Expanded (an unfolded inner display, a tablet) — navigation rail and the
 *    list and detail side by side, so unfolding reveals more information rather
 *    than the same information stretched.
 *
 * Selection and scroll live in the ViewModel and in rememberSaveable, so
 * crossing that boundary mid-session keeps the user exactly where they were.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MlevApp(
    state: MlevUiState,
    priceCount: Int,
    onSport: (Sport) -> Unit,
    onSelectFixture: (String?) -> Unit,
    onFilter: (EdgeFilter) -> Unit,
    onPrice: (String, MarketSide, String) -> Unit,
    onRefresh: () -> Unit,
    onDismissMessage: () -> Unit,
    viewModel: MlevViewModel,
) {
    val widthClass = currentWindowAdaptiveInfo().windowSizeClass.windowWidthSizeClass
    val expanded = widthClass != WindowWidthSizeClass.COMPACT

    var destination by rememberSaveable { mutableStateOf(Destination.MARKETS) }
    // In compact the detail is a separate page; expanded shows both at once.
    var showingDetail by rememberSaveable { mutableStateOf(false) }

    // Back goes back through the app before it leaves it.
    //
    // Nothing handled it before, so every press closed the app outright: from
    // Settings, from About, and — worst of it — from a fixture detail on a
    // phone, where the detail is a page the user navigated to and back is the
    // obvious way out of it. On a compact width that made the detail a trap
    // with one exit, the bottom bar. Expanded is different and deliberately
    // unhandled: the list and the detail are on screen together, so there is
    // nothing to pop, and back should leave.
    val detailIsAPage = !expanded && showingDetail
    BackHandler(enabled = destination != Destination.MARKETS || detailIsAPage) {
        if (destination != Destination.MARKETS) {
            destination = Destination.MARKETS
        } else {
            showingDetail = false
        }
    }

    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(state.message) {
        state.message?.let {
            snackbar.showSnackbar(it)
            onDismissMessage()
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        topBar = {
            TopAppBar(
                title = {
                    if (destination == Destination.MARKETS) {
                        SportSwitcher(state.sport, onSport)
                    } else {
                        Text(destination.label)
                    }
                },
                actions = {
                    if (state.refreshing) {
                        CircularProgressIndicator(
                            Modifier.padding(horizontal = 16.dp).then(Modifier),
                            strokeWidth = 2.dp,
                        )
                    } else {
                        IconButton(onClick = onRefresh) {
                            Icon(Icons.Default.Refresh, contentDescription = "Refresh predictions")
                        }
                    }
                },
            )
        },
        bottomBar = {
            if (!expanded) {
                NavigationBar {
                    Destination.entries.forEach { item ->
                        NavigationBarItem(
                            selected = destination == item,
                            onClick = { destination = item; showingDetail = false },
                            icon = { Icon(iconFor(item), contentDescription = item.label) },
                            label = { Text(item.label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        Row(Modifier.fillMaxSize().padding(padding).consumeWindowInsets(padding)) {
            if (expanded) {
                NavigationRail {
                    Destination.entries.forEach { item ->
                        NavigationRailItem(
                            selected = destination == item,
                            onClick = { destination = item },
                            icon = { Icon(iconFor(item), contentDescription = item.label) },
                            label = { Text(item.label) },
                        )
                    }
                }
                VerticalDivider()
            }

            when (destination) {
                Destination.MARKETS -> MarketsPane(
                    state = state,
                    expanded = expanded,
                    showingDetail = showingDetail,
                    onShowDetail = { showingDetail = it },
                    onSelectFixture = onSelectFixture,
                    onFilter = onFilter,
                    onPrice = onPrice,
                    viewModel = viewModel,
                )
                Destination.SETTINGS -> SettingsScreen(
                    settings = state.settings,
                    bundle = state.bundle,
                    priceCount = priceCount,
                    onTheme = viewModel::setThemeMode,
                    onDynamic = viewModel::setDynamicColor,
                    onOddsFormat = viewModel::setOddsFormat,
                    onStake = viewModel::setStake,
                    onBundleUrl = viewModel::setBundleUrl,
                    onClearPrices = viewModel::clearPrices,
                    onRefresh = onRefresh,
                    modifier = Modifier.fillMaxSize(),
                )
                Destination.ABOUT -> AboutScreen(state.bundle, Modifier.fillMaxSize())
            }
        }
    }
}

@Composable
private fun MarketsPane(
    state: MlevUiState,
    expanded: Boolean,
    showingDetail: Boolean,
    onShowDetail: (Boolean) -> Unit,
    onSelectFixture: (String?) -> Unit,
    onFilter: (EdgeFilter) -> Unit,
    onPrice: (String, MarketSide, String) -> Unit,
    viewModel: MlevViewModel,
) {
    if (state.fixtures.isEmpty()) {
        Box(Modifier.fillMaxSize().padding(20.dp), contentAlignment = Alignment.Center) {
            NoteCard(
                if (!state.loaded) "Loading predictions…"
                else "No predictions yet. Pull them in with the refresh button, and " +
                    "check the address in Settings if nothing arrives.",
                if (state.loaded) NoteTone.CAUTION else NoteTone.INFO,
            )
        }
        return
    }

    // The best EV on any side of any market, per fixture — so the list can lead
    // with where the value is instead of making you open every game.
    val bestEdges = remember(state.fixtures, state.prices, state.settings) {
        state.fixtures.associate { entry ->
            entry.fixture.id to entry.markets.flatMap { market ->
                market.sides.mapNotNull { side ->
                    val typed = state.prices[side.key(entry.fixture.id)].orEmpty()
                    val opposing = market.sides.firstOrNull { it != side }
                        ?.let { state.prices[it.key(entry.fixture.id)] }
                    comparisonFor(side, typed, opposing, state.settings.oddsFormat, state.settings.stake)
                        ?.evPerStake
                }
            }.maxOrNull()
        }.filterValues { it != null }.mapValues { it.value!! }
    }

    val selected = state.selected

    if (expanded) {
        Row(Modifier.fillMaxSize()) {
            FixtureList(
                fixtures = state.fixtures,
                selectedId = selected?.fixture?.id,
                bestEdges = bestEdges,
                onSelect = onSelectFixture,
                modifier = Modifier.weight(0.38f),
            )
            VerticalDivider()
            if (selected != null) {
                Column(Modifier.weight(0.62f)) {
                    FilterRow(state.filter, onFilter)
                    FixtureDetail(
                        entry = selected,
                        prices = state.prices,
                        filter = state.filter,
                        oddsFormat = state.settings.oddsFormat,
                        stake = state.settings.stake,
                        onPriceChange = { side, odds -> onPrice(selected.fixture.id, side, odds) },
                    )
                }
            }
        }
    } else {
        if (showingDetail && selected != null) {
            Column(Modifier.fillMaxSize()) {
                FilterRow(state.filter, onFilter)
                FixtureDetail(
                    entry = selected,
                    prices = state.prices,
                    filter = state.filter,
                    oddsFormat = state.settings.oddsFormat,
                    stake = state.settings.stake,
                    onPriceChange = { side, odds -> onPrice(selected.fixture.id, side, odds) },
                )
            }
        } else {
            FixtureList(
                fixtures = state.fixtures,
                selectedId = selected?.fixture?.id,
                bestEdges = bestEdges,
                onSelect = { onSelectFixture(it); onShowDetail(true) },
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SportSwitcher(sport: Sport, onSport: (Sport) -> Unit) {
    SingleChoiceSegmentedButtonRow {
        Sport.entries.forEachIndexed { index, option ->
            SegmentedButton(
                selected = sport == option,
                onClick = { onSport(option) },
                shape = SegmentedButtonDefaults.itemShape(index, Sport.entries.size),
            ) {
                Text(if (option == Sport.EPL) "EPL" else option.label)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FilterRow(filter: EdgeFilter, onFilter: (EdgeFilter) -> Unit) {
    SingleChoiceSegmentedButtonRow(
        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        EdgeFilter.entries.forEachIndexed { index, option ->
            SegmentedButton(
                selected = filter == option,
                onClick = { onFilter(option) },
                shape = SegmentedButtonDefaults.itemShape(index, EdgeFilter.entries.size),
            ) {
                Text(
                    when (option) {
                        EdgeFilter.ALL -> "All"
                        EdgeFilter.PRICED -> "Priced"
                        EdgeFilter.POSITIVE -> "+EV"
                    }
                )
            }
        }
    }
}

private fun iconFor(destination: Destination) = when (destination) {
    Destination.MARKETS -> Icons.Default.SportsFootball
    Destination.SETTINGS -> Icons.Default.Settings
    Destination.ABOUT -> Icons.Default.Info
}
