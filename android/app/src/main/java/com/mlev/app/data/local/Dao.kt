package com.mlev.app.data.local

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface BundleDao {
    @Query("SELECT * FROM bundles WHERE sport = :sport")
    fun observe(sport: String): Flow<BundleEntity?>

    @Query("SELECT * FROM bundles")
    fun observeAll(): Flow<List<BundleEntity>>

    @Query("SELECT * FROM bundles WHERE sport = :sport")
    suspend fun get(sport: String): BundleEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(bundle: BundleEntity)
}

@Dao
interface PriceDao {
    @Query("SELECT * FROM prices WHERE sport = :sport")
    fun observe(sport: String): Flow<List<PriceEntity>>

    @Query("SELECT * FROM prices")
    fun observeAll(): Flow<List<PriceEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(price: PriceEntity)

    @Query("DELETE FROM prices WHERE `key` = :key")
    suspend fun deleteByKey(key: String)

    @Query("DELETE FROM prices WHERE sport = :sport")
    suspend fun clearSport(sport: String)

    @Query("SELECT COUNT(*) FROM prices")
    suspend fun count(): Int
}

@Dao
interface NoteDao {
    @Query("SELECT * FROM notes WHERE sport = :sport")
    fun observe(sport: String): Flow<List<NoteEntity>>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(note: NoteEntity)

    @Delete
    suspend fun delete(note: NoteEntity)
}
