package com.mlev.app

import android.app.Application
import android.util.Log
import androidx.work.Configuration
import com.mlev.app.data.local.MlevDatabase
import com.mlev.app.work.SyncWorker

/**
 * Application entry point.
 *
 * Two deliberate choices here, both learned the hard way:
 *
 * 1. **WorkManager is initialised on demand**, via [Configuration.Provider],
 *    with its automatic initialiser removed from the manifest. Relying on the
 *    startup ContentProvider having already run before `onCreate` is an
 *    ordering assumption, and when it does not hold `WorkManager.getInstance`
 *    throws before the app has drawn anything.
 *
 * 2. **Scheduling is wrapped.** Background sync is a convenience; the app is
 *    perfectly usable without it because every prediction is already cached.
 *    Nothing optional in `onCreate` should ever be able to stop the app
 *    opening, so a failure here is logged and swallowed rather than thrown.
 */
class MlevApplication : Application(), Configuration.Provider {

    val database: MlevDatabase by lazy { MlevDatabase.get(this) }

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setMinimumLoggingLevel(if (BuildConfig.DEBUG) Log.DEBUG else Log.WARN)
            .build()

    override fun onCreate() {
        super.onCreate()
        runCatching { SyncWorker.schedule(this) }
            .onFailure { Log.w(TAG, "Background sync could not be scheduled", it) }
    }

    private companion object { const val TAG = "MlevApplication" }
}
