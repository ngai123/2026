package com.digitalngai.mirror.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Notes
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.digitalngai.mirror.data.local.JournalType
import com.digitalngai.mirror.ui.AppViewModel
import com.digitalngai.mirror.ui.TimelineItem
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun TimelineScreen(viewModel: AppViewModel) {
    val items by viewModel.timeline.collectAsState()
    val timeFmt = remember { SimpleDateFormat("MMM d, HH:mm", Locale.getDefault()) }

    if (items.isEmpty()) {
        Column(
            Modifier.fillMaxWidth().padding(32.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text("Nothing logged yet today. Talk into the mic, add a journal entry, or complete a todo.")
        }
        return
    }

    LazyColumn(
        contentPadding = PaddingValues(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        items(items) { item ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    val (icon, label) = when (item) {
                        is TimelineItem.Journal -> when (item.entry.type) {
                            JournalType.VOICE -> Icons.Filled.Mic to "Voice memo"
                            JournalType.CHECKIN -> Icons.Filled.Notes to "Check-in"
                            JournalType.TEXT -> Icons.Filled.Notes to "Journal"
                        }
                        is TimelineItem.TodoDone -> Icons.Filled.CheckCircle to "Completed"
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(icon, contentDescription = null)
                        Text("  $label", style = MaterialTheme.typography.labelLarge)
                    }
                    Text(timeFmt.format(Date(item.timestamp)), style = MaterialTheme.typography.bodySmall)
                    when (item) {
                        is TimelineItem.Journal -> {
                            item.entry.promptText?.let { Text("Prompt: $it") }
                            item.entry.text?.let { Text(it) }
                            item.entry.audioFilePath?.let { Text("Audio: ${it.substringAfterLast('/')}") }
                        }
                        is TimelineItem.TodoDone -> Text(item.todo.title)
                    }
                }
            }
        }
    }
}
