package com.mlev.app.work

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.glance.appwidget.updateAll
import com.mlev.app.data.local.MlevDatabase
import com.mlev.app.data.prefs.SettingsRepository
import com.mlev.app.data.repository.MlevRepository
import com.mlev.app.domain.model.Sport
import com.mlev.app.widget.EdgeWidget
import kotlinx.coroutines.flow.first
import java.util.concurrent.TimeUnit

/**
 * Keeps the cached bundles current in the background.
 *
 * Scheduled rather than polled: predictions change when a new one is published,
 * which is once or twice a week, so a periodic job with a network constraint is
 * the right shape. It never wakes the device on its own — WorkManager runs it
 * when the phone is already awake and connected.
 *
 * A failure retries with backoff and leaves the existing bundle alone. Stale
 * predictions are far more useful than an empty screen.
 */
class SyncWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val repository = MlevRepository(MlevDatabase.get(applicationContext))
        val url = SettingsRepository(applicationContext).settings.first().bundleUrl

        val failures = Sport.entries.mapNotNull { repository.refresh(it, url) }

        // The widget reads the same database, so refresh it once the data moved.
        runCatching { EdgeWidget().updateAll(applicationContext) }

        return when {
            failures.isEmpty() -> Result.success()
            // Every sport failed: probably offline, so let WorkManager back off
            // and try again rather than burning the attempt.
            failures.size == Sport.entries.size -> Result.retry()
            else -> Result.success()
        }
    }

    companion object {
        private const val NAME = "mlev-bundle-sync"

        /** Idempotent: safe to call on every app start. */
        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<SyncWorker>(12, TimeUnit.HOURS)
                .setConstraints(
                    Constraints.Builder()
                        .setRequiredNetworkType(NetworkType.CONNECTED)
                        .build()
                )
                .build()

            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                NAME,
                // KEEP, so an app update does not reset the schedule and cause a
                // burst of syncs across every install.
                ExistingPeriodicWorkPolicy.KEEP,
                request,
            )
        }
    }
}
