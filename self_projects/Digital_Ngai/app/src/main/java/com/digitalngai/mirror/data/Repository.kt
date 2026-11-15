package com.digitalngai.mirror.data

import android.content.Context
import com.digitalngai.mirror.data.local.AppDatabase
import com.digitalngai.mirror.data.local.JournalEntry
import com.digitalngai.mirror.data.local.LocationPing
import com.digitalngai.mirror.data.local.TodoItem
import kotlinx.coroutines.flow.Flow

/**
 * Single access point for local data. Kept thin on purpose: screens talk to
 * this, this talks to Room. Cloud sync (Firebase) will hook in here later
 * without touching the UI layer.
 */
class Repository(context: Context) {
    private val db = AppDatabase.get(context)

    // Location
    suspend fun logLocation(ping: LocationPing) = db.locationDao().insert(ping)
    fun locationsBetween(from: Long, to: Long): Flow<List<LocationPing>> =
        db.locationDao().between(from, to)
    suspend fun locationsBetweenSync(from: Long, to: Long) = db.locationDao().betweenSync(from, to)
    suspend fun latestLocation() = db.locationDao().latest()

    // Todos
    suspend fun addTodo(item: TodoItem) = db.todoDao().insert(item)
    suspend fun updateTodo(item: TodoItem) = db.todoDao().update(item)
    suspend fun deleteTodo(id: Long) = db.todoDao().delete(id)
    fun observeTodos(): Flow<List<TodoItem>> = db.todoDao().observeAll()
    suspend fun todosBetweenSync(from: Long, to: Long) = db.todoDao().betweenSync(from, to)

    // Journal
    suspend fun addJournalEntry(entry: JournalEntry) = db.journalDao().insert(entry)
    suspend fun updateJournalEntry(entry: JournalEntry) = db.journalDao().update(entry)
    suspend fun deleteJournalEntry(id: Long) = db.journalDao().delete(id)
    fun observeJournal(): Flow<List<JournalEntry>> = db.journalDao().observeAll()
    suspend fun journalBetweenSync(from: Long, to: Long) = db.journalDao().betweenSync(from, to)
}
