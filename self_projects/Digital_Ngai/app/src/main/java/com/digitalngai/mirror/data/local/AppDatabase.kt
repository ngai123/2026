package com.digitalngai.mirror.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import com.digitalngai.mirror.data.local.dao.JournalDao
import com.digitalngai.mirror.data.local.dao.LocationDao
import com.digitalngai.mirror.data.local.dao.TodoDao

@Database(
    entities = [LocationPing::class, TodoItem::class, JournalEntry::class],
    version = 1,
    exportSchema = false
)
@TypeConverters(Converters::class)
abstract class AppDatabase : RoomDatabase() {
    abstract fun locationDao(): LocationDao
    abstract fun todoDao(): TodoDao
    abstract fun journalDao(): JournalDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        fun get(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "digital_ngai.db"
                ).build().also { instance = it }
            }
    }
}
