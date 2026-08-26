package com.mlev.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.mlev.app.data.prefs.OddsFormat
import com.mlev.app.data.prefs.Settings
import com.mlev.app.data.prefs.SettingsRepository
import com.mlev.app.data.prefs.ThemeMode
import com.mlev.app.data.repository.MlevRepository
import com.mlev.app.domain.math.Odds
import com.mlev.app.domain.model.BundleInfo
import com.mlev.app.domain.model.FixtureMarkets
import com.mlev.app.domain.model.MarketSide
import com.mlev.app.domain.model.Sport
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/** What the user is filtering the market list down to. */
enum class EdgeFilter { ALL, PRICED, POSITIVE }

/** Everything one screen needs, in one immutable snapshot. */
data class MlevUiState(
    val sport: Sport = Sport.NFL,
    val fixtures: List<FixtureMarkets> = emptyList(),
    val bundle: BundleInfo? = null,
    val prices: Map<String, String> = emptyMap(),
    val settings: Settings = Settings(),
    val selectedFixtureId: String? = null,
    val filter: EdgeFilter = EdgeFilter.ALL,
    val refreshing: Boolean = false,
    val message: String? = null,
    val loaded: Boolean = false,
) {
    val selected: FixtureMarkets?
        get() = fixtures.firstOrNull { it.fixture.id == selectedFixtureId } ?: fixtures.firstOrNull()
}

/**
 * The app's state holder.
 *
 * Selection, filter and typed prices live here rather than in composables, which
 * is what makes folding the phone a layout change and not a reset: the ViewModel
 * outlives configuration changes, and [SavedStateHandle] carries the selection
 * through process death as well.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class MlevViewModel(
    application: Application,
    private val handle: SavedStateHandle,
) : AndroidViewModel(application) {

    private val repository = MlevRepository.create(application)
    private val settingsRepo = SettingsRepository(application)

    private val sport = MutableStateFlow(
        Sport.from(handle.get<String>(KEY_SPORT) ?: "nfl")
    )
    private val selection = MutableStateFlow(handle.get<String>(KEY_SELECTED))
    private val filter = MutableStateFlow(
        runCatching { EdgeFilter.valueOf(handle.get<String>(KEY_FILTER) ?: "ALL") }
            .getOrDefault(EdgeFilter.ALL)
    )
    private val transient = MutableStateFlow(TransientState())

    private data class TransientState(
        val refreshing: Boolean = false,
        val message: String? = null,
        val loaded: Boolean = false,
    )

    val state: StateFlow<MlevUiState> = combine(
        sport.flatMapLatest { repository.observeFixtures(it) },
        sport.flatMapLatest { repository.observeBundle(it) },
        sport.flatMapLatest { repository.observePrices(it) },
        settingsRepo.settings,
        combine(sport, selection, filter, transient) { s, sel, f, t -> Quad(s, sel, f, t) },
    ) { fixtures, bundle, prices, settings, quad ->
        MlevUiState(
            sport = quad.sport,
            fixtures = fixtures,
            bundle = bundle,
            prices = prices,
            settings = settings,
            selectedFixtureId = quad.selection ?: fixtures.firstOrNull()?.fixture.let { it?.id },
            filter = quad.filter,
            refreshing = quad.transient.refreshing,
            message = quad.transient.message,
            loaded = quad.transient.loaded || bundle != null,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), MlevUiState())

    private data class Quad(
        val sport: Sport,
        val selection: String?,
        val filter: EdgeFilter,
        val transient: TransientState,
    )

    init {
        // First launch with no cached bundle: try once, quietly.
        viewModelScope.launch {
            settingsRepo.settings.let { flow ->
                val current = state.value
                if (current.bundle == null) refresh()
            }
        }
    }

    // ------------------------------------------------------------- actions

    fun selectSport(next: Sport) {
        sport.value = next
        handle[KEY_SPORT] = next.key
        // Selection belongs to a sport, so clear it rather than pointing at a
        // fixture from the other one.
        selection.value = null
        handle[KEY_SELECTED] = null
        viewModelScope.launch { settingsRepo.setLastSport(next.key) }
    }

    fun selectFixture(id: String?) {
        selection.value = id
        handle[KEY_SELECTED] = id
    }

    fun setFilter(next: EdgeFilter) {
        filter.value = next
        handle[KEY_FILTER] = next.name
    }

    fun setPrice(fixtureId: String, side: MarketSide, odds: String) {
        viewModelScope.launch {
            repository.savePrice(sport.value, fixtureId, side.market, side.side, odds)
        }
    }

    fun refresh() {
        if (transient.value.refreshing) return
        viewModelScope.launch {
            transient.value = transient.value.copy(refreshing = true, message = null)
            val url = settingsRepo.settings.let { state.value.settings.bundleUrl }
            val error = repository.refresh(sport.value, url)
            transient.value = TransientState(
                refreshing = false,
                message = error,
                loaded = true,
            )
        }
    }

    fun refreshAll() {
        viewModelScope.launch {
            transient.value = transient.value.copy(refreshing = true, message = null)
            val url = state.value.settings.bundleUrl
            val errors = Sport.entries.mapNotNull { repository.refresh(it, url) }
            transient.value = TransientState(
                refreshing = false,
                message = errors.firstOrNull(),
                loaded = true,
            )
        }
    }

    fun dismissMessage() { transient.value = transient.value.copy(message = null) }

    fun setThemeMode(mode: ThemeMode) = viewModelScope.launch { settingsRepo.setThemeMode(mode) }
    fun setDynamicColor(on: Boolean) = viewModelScope.launch { settingsRepo.setDynamicColor(on) }
    fun setOddsFormat(f: OddsFormat) = viewModelScope.launch { settingsRepo.setOddsFormat(f) }
    fun setStake(stake: Double) = viewModelScope.launch { settingsRepo.setStake(stake) }
    fun setBundleUrl(url: String) = viewModelScope.launch { settingsRepo.setBundleUrl(url) }
    fun clearPrices() = viewModelScope.launch { repository.clearPrices(sport.value) }

    /**
     * Compare a typed price against the model, including the other side of the
     * same market when it has also been priced — that is what enables the
     * de-vigged number.
     */
    fun compare(
        side: MarketSide,
        odds: String,
        opposing: String?,
        format: OddsFormat,
        stake: Double,
    ): Odds.Comparison? {
        val value = odds.trim().toDoubleOrNull() ?: return null
        val other = opposing?.trim()?.toDoubleOrNull()
        return runCatching {
            Odds.compare(
                probability = side.probability,
                bookOdds = value,
                format = if (format == OddsFormat.AMERICAN) Odds.Format.AMERICAN else Odds.Format.DECIMAL,
                pushProbability = side.pushProbability,
                opposingOdds = other,
                stake = stake,
            )
        }.getOrNull()
    }

    companion object {
        private const val KEY_SPORT = "sport"
        private const val KEY_SELECTED = "selected_fixture"
        private const val KEY_FILTER = "edge_filter"
    }
}
