package com.mlev.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import com.mlev.app.ui.MlevApp
import com.mlev.app.ui.MlevViewModel
import com.mlev.app.ui.theme.MlevTheme

/**
 * The single activity.
 *
 * `configChanges` in the manifest keeps the activity alive through folding, so
 * the window simply resizes and Compose reflows. State still lives in the
 * ViewModel and in rememberSaveable, which is what makes it correct even when
 * Android does recreate the activity — on a theme change, or after being killed
 * in the background.
 */
class MainActivity : ComponentActivity() {

    private val viewModel: MlevViewModel by viewModels {
        androidx.lifecycle.ViewModelProvider.AndroidViewModelFactory.getInstance(application)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen()
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)

        setContent {
            val state by viewModel.state.collectAsState()
            MlevTheme(
                themeMode = state.settings.themeMode,
                dynamicColor = state.settings.dynamicColor,
            ) {
                val priceCount = remember(state.prices) { state.prices.size }
                MlevApp(
                    state = state,
                    priceCount = priceCount,
                    onSport = viewModel::selectSport,
                    onSelectFixture = viewModel::selectFixture,
                    onFilter = viewModel::setFilter,
                    onPrice = { fixtureId, side, odds -> viewModel.setPrice(fixtureId, side, odds) },
                    onRefresh = viewModel::refreshAll,
                    onDismissMessage = viewModel::dismissMessage,
                    viewModel = viewModel,
                )
            }
        }
    }
}
