package com.digitalngai.mirror.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.digitalngai.mirror.DigitalNgaiApp
import com.digitalngai.mirror.ai.ClassifiedEntry
import com.digitalngai.mirror.ai.EntryClassifier
import com.digitalngai.mirror.ai.HeuristicClassifier
import com.digitalngai.mirror.data.local.JournalEntry
import com.digitalngai.mirror.data.local.JournalType
import com.digitalngai.mirror.data.local.LocationPing
import com.digitalngai.mirror.data.local.TodoItem
import com.digitalngai.mirror.data.local.TodoPriority
import com.digitalngai.mirror.export.AiExporter
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.io.File
import java.util.concurrent.TimeUnit

class AppViewModel(application: Application) : AndroidViewModel(application) {
    private val app get() = getApplication<DigitalNgaiApp>()
    private val repo get() = app.repository
    private val exporter = AiExporter(application, app.repository)
    private val classifier: EntryClassifier = HeuristicClassifier()

    val todos: StateFlow<List<TodoItem>> = repo.observeTodos()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val journal: StateFlow<List<JournalEntry>> = repo.observeJournal()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val recentLocations: StateFlow<List<LocationPing>> = repo
        .locationsBetween(System.currentTimeMillis() - TimeUnit.DAYS.toMillis(1), Long.MAX_VALUE)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    // A unified, time-descending feed for the Timeline screen. Location pings
    // are deliberately excluded -- they live on the Map tab as a trail, not
    // as a wall of coordinate entries here.
    val timeline: StateFlow<List<TimelineItem>> = combineTimeline()

    private fun combineTimeline(): StateFlow<List<TimelineItem>> {
        return kotlinx.coroutines.flow.combine(journal, todos) { j, t ->
            val items = mutableListOf<TimelineItem>()
            j.forEach { items += TimelineItem.Journal(it) }
            t.filter { it.completedAt != null }.forEach { items += TimelineItem.TodoDone(it) }
            items.sortedByDescending { it.timestamp }
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())
    }

    private val _voiceCaptureMessage = MutableStateFlow<String?>(null)
    val voiceCaptureMessage: StateFlow<String?> = _voiceCaptureMessage.asStateFlow()

    /**
     * Entry point for the global mic button: a raw speech transcript comes
     * in, gets classified (currently a passthrough -- everything becomes a
     * journal note -- until an LLM is wired in), and is filed automatically.
     * No manual step after speaking.
     */
    fun handleVoiceTranscript(transcript: String) {
        viewModelScope.launch {
            when (val classified = classifier.classify(transcript)) {
                is ClassifiedEntry.Todo -> {
                    repo.addTodo(
                        TodoItem(
                            title = classified.title,
                            notes = classified.notes,
                            createdAt = System.currentTimeMillis()
                        )
                    )
                    _voiceCaptureMessage.value = "Added todo: ${classified.title}"
                }
                is ClassifiedEntry.JournalNote -> {
                    repo.addJournalEntry(
                        JournalEntry(
                            timestamp = System.currentTimeMillis(),
                            type = JournalType.TEXT,
                            text = classified.text,
                            promptText = "Voice capture"
                        )
                    )
                    _voiceCaptureMessage.value = "Logged: ${classified.text}"
                }
            }
        }
    }

    fun voiceCaptureError(message: String) {
        _voiceCaptureMessage.value = message
    }

    fun clearVoiceCaptureMessage() {
        _voiceCaptureMessage.value = null
    }

    fun addTodo(title: String, notes: String?, priority: TodoPriority) {
        viewModelScope.launch {
            repo.addTodo(
                TodoItem(
                    title = title,
                    notes = notes,
                    createdAt = System.currentTimeMillis(),
                    priority = priority
                )
            )
        }
    }

    fun toggleTodo(item: TodoItem) {
        viewModelScope.launch {
            repo.updateTodo(
                item.copy(completedAt = if (item.completedAt == null) System.currentTimeMillis() else null)
            )
        }
    }

    fun deleteTodo(id: Long) {
        viewModelScope.launch { repo.deleteTodo(id) }
    }

    fun editTodo(id: Long, title: String, notes: String?) {
        viewModelScope.launch {
            val current = todos.value.firstOrNull { it.id == id } ?: return@launch
            repo.updateTodo(current.copy(title = title, notes = notes))
        }
    }

    fun addTextJournalEntry(text: String, promptText: String? = null) {
        viewModelScope.launch {
            repo.addJournalEntry(
                JournalEntry(
                    timestamp = System.currentTimeMillis(),
                    type = if (promptText != null) JournalType.CHECKIN else JournalType.TEXT,
                    text = text,
                    promptText = promptText
                )
            )
        }
    }

    fun addVoiceJournalEntry(file: File) {
        viewModelScope.launch {
            repo.addJournalEntry(
                JournalEntry(
                    timestamp = System.currentTimeMillis(),
                    type = JournalType.VOICE,
                    audioFilePath = file.absolutePath
                )
            )
        }
    }

    fun deleteJournalEntry(id: Long) {
        viewModelScope.launch { repo.deleteJournalEntry(id) }
    }

    fun editJournalEntry(id: Long, newText: String) {
        viewModelScope.launch {
            val current = journal.value.firstOrNull { it.id == id } ?: return@launch
            repo.updateJournalEntry(current.copy(text = newText))
        }
    }

    suspend fun exportLastDays(days: Int): File {
        val to = System.currentTimeMillis()
        val from = to - TimeUnit.DAYS.toMillis(days.toLong())
        return exporter.exportRange(from, to)
    }

    fun shareUri(file: File) = exporter.shareUri(file)

    companion object {
        fun factory(application: Application): ViewModelProvider.Factory =
            object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : ViewModel> create(modelClass: Class<T>): T =
                    AppViewModel(application) as T
            }
    }
}

sealed class TimelineItem(val timestamp: Long) {
    data class Journal(val entry: JournalEntry) : TimelineItem(entry.timestamp)
    data class TodoDone(val todo: TodoItem) : TimelineItem(todo.completedAt ?: todo.createdAt)
}
