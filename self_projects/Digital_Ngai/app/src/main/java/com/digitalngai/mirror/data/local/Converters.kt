package com.digitalngai.mirror.data.local

import androidx.room.TypeConverter

class Converters {
    @TypeConverter
    fun fromTodoPriority(value: TodoPriority): String = value.name

    @TypeConverter
    fun toTodoPriority(value: String): TodoPriority = TodoPriority.valueOf(value)

    @TypeConverter
    fun fromJournalType(value: JournalType): String = value.name

    @TypeConverter
    fun toJournalType(value: String): JournalType = JournalType.valueOf(value)
}
