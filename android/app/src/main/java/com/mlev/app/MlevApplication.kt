package com.mlev.app

import android.app.Application
import com.mlev.app.data.local.MlevDatabase
import com.mlev.app.work.SyncWorker

/**
 * Application entry point.
 *
 * Deliberately thin: the database is created lazily on first use rather than
 * here, so a cold start does not touch disk before the first frame. Scheduling
 * the sync is idempotent, so doing it on every launch is correct and cheap.
 */
class MlevApplication : Application() {

    val database: MlevDatabase by lazy { MlevDatabase.get(this) }

    override fun onCreate() {
        super.onCreate()
        SyncWorker.schedule(this)
    }
}
