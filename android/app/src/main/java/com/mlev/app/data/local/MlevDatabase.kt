package com.mlev.app.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/**
 * The app's persistent store.
 *
 * Migration policy: never destructive. Saved prices and notes are the user's own
 * work, and an app update that silently dropped them would be a bug, not a
 * simplification. Every schema change gets a real migration appended to
 * [MIGRATIONS], and older versions must be able to reach the current one by
 * running them in order.
 */
@Database(
    entities = [BundleEntity::class, PriceEntity::class, NoteEntity::class],
    version = 1,
    exportSchema = true,
)
abstract class MlevDatabase : RoomDatabase() {

    abstract fun bundles(): BundleDao
    abstract fun prices(): PriceDao
    abstract fun notes(): NoteDao

    companion object {
        private const val NAME = "mlev.db"

        /**
         * Append here; never renumber. An example of the shape a future one takes:
         *
         * val MIGRATION_1_2 = object : Migration(1, 2) {
         *     override fun migrate(db: SupportSQLiteDatabase) {
         *         db.execSQL("ALTER TABLE prices ADD COLUMN stake REAL NOT NULL DEFAULT 100.0")
         *     }
         * }
         */
        val MIGRATIONS: Array<Migration> = emptyArray()

        @Volatile private var instance: MlevDatabase? = null

        fun get(context: Context): MlevDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext, MlevDatabase::class.java, NAME,
            )
                .addMigrations(*MIGRATIONS)
                // Deliberately NOT fallbackToDestructiveMigration(): a missing
                // migration should fail loudly in testing rather than wipe data
                // on a user's phone.
                .build()
                .also { instance = it }
        }
    }
}
