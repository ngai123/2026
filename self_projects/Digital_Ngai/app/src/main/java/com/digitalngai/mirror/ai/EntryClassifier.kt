package com.digitalngai.mirror.ai

sealed class ClassifiedEntry {
    data class Todo(val title: String, val notes: String? = null) : ClassifiedEntry()
    data class JournalNote(val text: String) : ClassifiedEntry()
}

/**
 * Turns a raw voice transcript into something structured -- a todo, a
 * journal note, etc. This is the seam where a real LLM call (Claude) plugs
 * in once an API key is available.
 */
interface EntryClassifier {
    suspend fun classify(transcript: String): ClassifiedEntry
}

class PassthroughClassifier : EntryClassifier {
    override suspend fun classify(transcript: String): ClassifiedEntry =
        ClassifiedEntry.JournalNote(transcript)
}

/**
 * Keyword-based stand-in for real LLM classification. Good enough to make
 * "remind me to..." voice captures land as todos instead of journal notes
 * without needing an API key. Swap for an LLM-backed classifier later --
 * nothing else in the app needs to change since both implement
 * [EntryClassifier].
 */
class HeuristicClassifier : EntryClassifier {
    private val todoPrefixes = listOf(
        "remind me to ",
        "reminder to ",
        "todo ",
        "to do ",
        "i need to ",
        "i have to ",
        "don't forget to ",
        "dont forget to ",
        "add a task to ",
        "add task to ",
        "task: ",
        "note to self, remind me to "
    )

    override suspend fun classify(transcript: String): ClassifiedEntry {
        val trimmed = transcript.trim()
        val lower = trimmed.lowercase()

        val matchedPrefix = todoPrefixes.firstOrNull { lower.startsWith(it) }
        if (matchedPrefix != null) {
            val title = trimmed.substring(matchedPrefix.length).trim().replaceFirstChar { it.uppercase() }
            if (title.isNotBlank()) return ClassifiedEntry.Todo(title = title)
        }

        return ClassifiedEntry.JournalNote(trimmed)
    }
}
