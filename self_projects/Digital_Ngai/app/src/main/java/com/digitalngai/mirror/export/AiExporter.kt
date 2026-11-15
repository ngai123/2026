package com.digitalngai.mirror.export

import android.content.Context
import androidx.core.content.FileProvider
import com.digitalngai.mirror.data.Repository
import com.digitalngai.mirror.usage.UsageStatsHelper
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Dumps a date range of everything the app knows -- location, todos,
 * journal/voice/check-ins -- into one structured JSON file. This is the
 * hand-off point for feeding a personal AI assistant real context about
 * the user's day instead of it guessing.
 */
class AiExporter(private val context: Context, private val repo: Repository) {

    suspend fun exportRange(fromMillis: Long, toMillis: Long): File {
        val root = JSONObject()
        val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)

        root.put("generated_at", iso.format(Date()))
        root.put("range_from", iso.format(Date(fromMillis)))
        root.put("range_to", iso.format(Date(toMillis)))

        val locations = JSONArray()
        repo.locationsBetweenSync(fromMillis, toMillis).forEach { ping ->
            locations.put(JSONObject().apply {
                put("timestamp", iso.format(Date(ping.timestamp)))
                put("lat", ping.latitude)
                put("lng", ping.longitude)
                put("accuracy_m", ping.accuracyMeters)
                ping.placeName?.let { put("place", it) }
            })
        }
        root.put("locations", locations)

        val todos = JSONArray()
        repo.todosBetweenSync(fromMillis, toMillis).forEach { todo ->
            todos.put(JSONObject().apply {
                put("title", todo.title)
                todo.notes?.let { put("notes", it) }
                put("created_at", iso.format(Date(todo.createdAt)))
                todo.dueAt?.let { put("due_at", iso.format(Date(it))) }
                todo.completedAt?.let { put("completed_at", iso.format(Date(it))) }
                put("priority", todo.priority.name)
            })
        }
        root.put("todos", todos)

        val journal = JSONArray()
        repo.journalBetweenSync(fromMillis, toMillis).forEach { entry ->
            journal.put(JSONObject().apply {
                put("timestamp", iso.format(Date(entry.timestamp)))
                put("type", entry.type.name)
                entry.promptText?.let { put("prompt", it) }
                entry.text?.let { put("text", it) }
                entry.audioFilePath?.let { put("audio_file", File(it).name) }
            })
        }
        root.put("journal", journal)

        val appUsage = JSONArray()
        UsageStatsHelper.usageBetween(context, fromMillis, toMillis).forEach { usage ->
            appUsage.put(JSONObject().apply {
                put("app", usage.label)
                put("package", usage.packageName)
                put("foreground_minutes", usage.foregroundMillis / 60000)
            })
        }
        root.put("screen_time", appUsage)

        val exportDir = File(context.getExternalFilesDir(null), "exports").apply { mkdirs() }
        val fileName = "digital_ngai_export_${System.currentTimeMillis()}.json"
        val file = File(exportDir, fileName)
        file.writeText(root.toString(2))
        return file
    }

    fun shareUri(file: File) =
        FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
}
