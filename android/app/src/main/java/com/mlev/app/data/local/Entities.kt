package com.mlev.app.data.local

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * A downloaded bundle, stored whole.
 *
 * The distribution parameters are kept as the original JSON rather than exploded
 * into columns: the app reconstructs distributions from them, and keeping the
 * payload intact means a schema change on the Python side does not force a Room
 * migration here. The columns are the things worth querying and showing.
 */
@Entity(tableName = "bundles")
data class BundleEntity(
    @PrimaryKey val sport: String,
    val schema: Int,
    val generatedAt: String,
    val trainedThrough: String,
    val trainingRows: Int,
    val fixtureCount: Int,
    val payload: String,
    val downloadedAt: Long,
)

/**
 * A price the user typed against one side of one market.
 *
 * This is the only genuinely user-created data in the app, so it is the thing an
 * APK update must never lose. Keyed by fixture, market and side, so it survives a
 * bundle refresh that keeps the same fixtures.
 */
@Entity(
    tableName = "prices",
    indices = [Index("fixtureId"), Index("sport")],
)
data class PriceEntity(
    @PrimaryKey val key: String,
    val fixtureId: String,
    val sport: String,
    val market: String,
    val side: String,
    val odds: String,
    val updatedAt: Long,
)

/** A note the user attached to a fixture. Small, but theirs. */
@Entity(tableName = "notes")
data class NoteEntity(
    @PrimaryKey val fixtureId: String,
    val sport: String,
    val text: String,
    val updatedAt: Long,
)
