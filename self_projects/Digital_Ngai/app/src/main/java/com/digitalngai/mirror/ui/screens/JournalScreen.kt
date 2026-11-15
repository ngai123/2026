package com.digitalngai.mirror.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.digitalngai.mirror.data.local.JournalEntry
import com.digitalngai.mirror.data.local.JournalType
import com.digitalngai.mirror.ui.AppViewModel
import com.digitalngai.mirror.voice.VoiceRecorder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun JournalScreen(viewModel: AppViewModel) {
    val entries by viewModel.journal.collectAsState()
    val context = LocalContext.current
    val recorder = remember { VoiceRecorder(context) }

    var text by remember { mutableStateOf("") }
    var isRecording by remember { mutableStateOf(false) }
    var editingEntry by remember { mutableStateOf<JournalEntry?>(null) }
    val timeFmt = remember { SimpleDateFormat("MMM d, HH:mm", Locale.getDefault()) }

    Column(Modifier.fillMaxWidth().padding(12.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text("What's on your mind?") },
                modifier = Modifier.weight(1f)
            )
            IconButton(onClick = {
                if (text.isNotBlank()) {
                    viewModel.addTextJournalEntry(text.trim())
                    text = ""
                }
            }) { Icon(Icons.Filled.Send, contentDescription = "Save") }

            IconButton(onClick = {
                val hasMicPermission = ContextCompat.checkSelfPermission(
                    context, Manifest.permission.RECORD_AUDIO
                ) == PackageManager.PERMISSION_GRANTED
                if (!hasMicPermission) return@IconButton

                if (isRecording) {
                    val file = recorder.stop()
                    isRecording = false
                    if (file != null && file.length() > 0) {
                        viewModel.addVoiceJournalEntry(file)
                    }
                } else {
                    recorder.start()
                    isRecording = true
                }
            }) {
                Icon(
                    if (isRecording) Icons.Filled.Stop else Icons.Filled.Mic,
                    contentDescription = if (isRecording) "Stop recording" else "Record voice memo"
                )
            }
        }

        androidx.compose.foundation.layout.Spacer(Modifier.padding(4.dp))

        LazyColumn(
            contentPadding = PaddingValues(vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            items(entries, key = { it.id }) { entry ->
                Card(Modifier.fillMaxWidth()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.padding(10.dp).weight(1f)) {
                            Text(timeFmt.format(Date(entry.timestamp)), style = MaterialTheme.typography.bodySmall)
                            entry.promptText?.let { Text("Prompt: $it", style = MaterialTheme.typography.labelMedium) }
                            when (entry.type) {
                                JournalType.VOICE -> Text("Voice memo: ${entry.audioFilePath?.substringAfterLast('/')}")
                                else -> entry.text?.let { Text(it) }
                            }
                        }
                        if (entry.type != JournalType.VOICE) {
                            IconButton(onClick = { editingEntry = entry }) {
                                Icon(Icons.Filled.Edit, contentDescription = "Edit entry")
                            }
                        }
                        IconButton(onClick = { viewModel.deleteJournalEntry(entry.id) }) {
                            Icon(Icons.Filled.Delete, contentDescription = "Delete entry")
                        }
                    }
                }
            }
        }
    }

    editingEntry?.let { entry ->
        EditJournalDialog(
            initialText = entry.text.orEmpty(),
            onDismiss = { editingEntry = null },
            onSave = { newText ->
                viewModel.editJournalEntry(entry.id, newText)
                editingEntry = null
            }
        )
    }
}

@Composable
private fun EditJournalDialog(
    initialText: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit
) {
    var text by remember { mutableStateOf(initialText) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit entry") },
        text = {
            OutlinedTextField(value = text, onValueChange = { text = it }, label = { Text("Text") })
        },
        confirmButton = {
            TextButton(onClick = { if (text.isNotBlank()) onSave(text.trim()) }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
}
