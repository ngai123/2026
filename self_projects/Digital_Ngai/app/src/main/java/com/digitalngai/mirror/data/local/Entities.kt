package com.digitalngai.mirror.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Raw GPS samples. Dense and unfiltered -- kept separate from the curated
 * timeline so the Timeline screen / AI export can stay readable while this
 * table still has full-resolution location history if needed later.
 */
@Entity(tableName = "location_pings")
data class LocationPing(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val timestamp: Long,
    val latitude: Double,
    val longitude: Double,
    val accuracyMeters: Float,
    val placeName: String? = null
)

enum class TodoPriority { LOW, NORMAL, HIGH }

@Entity(tableName = "todo_items")
data class TodoItem(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val title: String,
    val notes: String? = null,
    val createdAt: Long,
    val dueAt: Long? = null,
    val completedAt: Long? = null,
    val priority: TodoPriority = TodoPriority.NORMAL
)

enum class JournalType { TEXT, VOICE, CHECKIN }

/**
 * Everything that isn't a raw location ping or a todo: free-text notes,
 * voice memos, and answers to periodic "what are you doing?" check-ins.
 * This is the table an AI summarizer reads to understand a day.
 */
@Entity(tableName = "journal_entries")
data class JournalEntry(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val timestamp: Long,
    val type: JournalType,
    val text: String? = null,
    val audioFilePath: String? = null,
    val promptText: String? = null
)
