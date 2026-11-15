package com.digitalngai.mirror.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.Query
import androidx.room.Update
import com.digitalngai.mirror.data.local.JournalEntry
import com.digitalngai.mirror.data.local.LocationPing
import com.digitalngai.mirror.data.local.TodoItem
import kotlinx.coroutines.flow.Flow

@Dao
interface LocationDao {
    @Insert
    suspend fun insert(ping: LocationPing)

    @Query("SELECT * FROM location_pings WHERE timestamp BETWEEN :from AND :to ORDER BY timestamp DESC")
    fun between(from: Long, to: Long): Flow<List<LocationPing>>

    @Query("SELECT * FROM location_pings WHERE timestamp BETWEEN :from AND :to ORDER BY timestamp ASC")
    suspend fun betweenSync(from: Long, to: Long): List<LocationPing>

    @Query("SELECT * FROM location_pings ORDER BY timestamp DESC LIMIT 1")
    suspend fun latest(): LocationPing?
}

@Dao
interface TodoDao {
    @Insert
    suspend fun insert(item: TodoItem): Long

    @Update
    suspend fun update(item: TodoItem)

    @Query("SELECT * FROM todo_items ORDER BY (completedAt IS NOT NULL), dueAt IS NULL, dueAt ASC, createdAt DESC")
    fun observeAll(): Flow<List<TodoItem>>

    @Query("SELECT * FROM todo_items WHERE createdAt BETWEEN :from AND :to OR completedAt BETWEEN :from AND :to")
    suspend fun betweenSync(from: Long, to: Long): List<TodoItem>

    @Query("DELETE FROM todo_items WHERE id = :id")
    suspend fun delete(id: Long)
}

@Dao
interface JournalDao {
    @Insert
    suspend fun insert(entry: JournalEntry): Long

    @Update
    suspend fun update(entry: JournalEntry)

    @Query("SELECT * FROM journal_entries ORDER BY timestamp DESC")
    fun observeAll(): Flow<List<JournalEntry>>

    @Query("SELECT * FROM journal_entries WHERE timestamp BETWEEN :from AND :to ORDER BY timestamp ASC")
    suspend fun betweenSync(from: Long, to: Long): List<JournalEntry>

    @Query("DELETE FROM journal_entries WHERE id = :id")
    suspend fun delete(id: Long)
}
