package com.mlev.app

import android.app.Application
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelProvider
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.mlev.app.ui.MlevViewModel
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config

/**
 * Does the app actually start?
 *
 * Every other test in this module checks arithmetic, which is worth doing and
 * catches nothing about launching. This one drives the real Activity through
 * onCreate, the theme, the splash handover and the first composition, on the
 * JVM — the path where an app that computes perfectly can still die before
 * drawing a frame.
 *
 * It exists because a build shipped that crashed on every launch: the Activity
 * pinned AndroidViewModelFactory, which can only construct a ViewModel taking
 * (Application) or (), while MlevViewModel takes (Application, SavedStateHandle).
 * Nothing in a maths test could have seen that.
 */
@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class StartupTest {

    @Test
    fun `the launcher activity starts without crashing`() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                assertNotNull("the activity should exist after launch", activity)
            }
        }
    }

    @Test
    fun `the activity survives being recreated`() {
        // Folding, a theme change, or coming back from the background all take
        // this path when the system decides to recreate rather than resize.
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.recreate()
            scenario.onActivity { assertNotNull(it) }
        }
    }

    @Test
    fun `the view model can be built by the factory the activity actually uses`() {
        // The narrow version of the same bug: the default factory must be able
        // to supply a SavedStateHandle.
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            scenario.onActivity { activity ->
                val viewModel = ViewModelProvider(activity)[MlevViewModel::class.java]
                assertNotNull(viewModel.state.value)
            }
        }
    }

    @Test
    fun `the view model constructs directly with a saved state handle`() {
        val application = ApplicationProvider.getApplicationContext<Application>()
        val viewModel = MlevViewModel(application, SavedStateHandle())
        assertNotNull(viewModel.state.value)
    }
}
