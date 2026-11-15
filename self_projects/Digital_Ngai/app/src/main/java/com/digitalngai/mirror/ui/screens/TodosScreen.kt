package com.digitalngai.mirror.ui.screens

import android.Manifest
import android.content.pm.PackageManager
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.digitalngai.mirror.data.local.TodoItem
import com.digitalngai.mirror.data.local.TodoPriority
import com.digitalngai.mirror.ui.AppViewModel
import com.digitalngai.mirror.voice.VoiceCaptureController
import com.digitalngai.mirror.voice.VoiceCaptureState

@Composable
fun TodosScreen(viewModel: AppViewModel) {
    val todos by viewModel.todos.collectAsState()
    var showAddDialog by remember { mutableStateOf(false) }
    var editingTodo by remember { mutableStateOf<TodoItem?>(null) }

    Scaffold(
        floatingActionButton = {
            FloatingActionButton(onClick = { showAddDialog = true }) {
                Icon(Icons.Filled.Add, contentDescription = "Add todo")
            }
        }
    ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
            if (todos.isEmpty()) {
                Text(
                    "No todos yet. Tap + to add one, or say \"remind me to...\" into the mic.",
                    Modifier.padding(32.dp)
                )
            } else {
                LazyColumn(
                    contentPadding = PaddingValues(12.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    items(todos, key = { it.id }) { todo ->
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(
                                checked = todo.completedAt != null,
                                onCheckedChange = { viewModel.toggleTodo(todo) }
                            )
                            Column(
                                Modifier
                                    .weight(1f)
                                    .padding(vertical = 8.dp)
                            ) {
                                Text(
                                    todo.title,
                                    textDecoration = if (todo.completedAt != null) TextDecoration.LineThrough else null
                                )
                                todo.notes?.let {
                                    Text(it, style = MaterialTheme.typography.bodySmall)
                                }
                            }
                            IconButton(onClick = { editingTodo = todo }) {
                                Icon(Icons.Filled.Edit, contentDescription = "Edit")
                            }
                            IconButton(onClick = { viewModel.deleteTodo(todo.id) }) {
                                Icon(Icons.Filled.Delete, contentDescription = "Delete")
                            }
                        }
                    }
                }
            }
        }
    }

    if (showAddDialog) {
        TodoDialog(
            title = "New todo",
            initialTitle = "",
            initialNotes = "",
            onDismiss = { showAddDialog = false },
            onSave = { title, notes ->
                viewModel.addTodo(title, notes, TodoPriority.NORMAL)
                showAddDialog = false
            }
        )
    }

    editingTodo?.let { todo ->
        TodoDialog(
            title = "Edit todo",
            initialTitle = todo.title,
            initialNotes = todo.notes.orEmpty(),
            onDismiss = { editingTodo = null },
            onSave = { title, notes ->
                viewModel.editTodo(todo.id, title, notes)
                editingTodo = null
            }
        )
    }
}

@Composable
private fun TodoDialog(
    title: String,
    initialTitle: String,
    initialNotes: String,
    onDismiss: () -> Unit,
    onSave: (String, String?) -> Unit
) {
    var todoTitle by remember { mutableStateOf(initialTitle) }
    var notes by remember { mutableStateOf(initialNotes) }
    var isListening by remember { mutableStateOf(false) }
    val context = LocalContext.current

    val voiceController = remember {
        VoiceCaptureController(
            context = context,
            onState = { isListening = it == VoiceCaptureState.LISTENING },
            onResult = { transcript -> todoTitle = transcript },
            onError = { isListening = false }
        )
    }
    DisposableEffect(Unit) { onDispose { voiceController.cancel() } }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        value = todoTitle,
                        onValueChange = { todoTitle = it },
                        label = { Text("Title") },
                        modifier = Modifier.weight(1f)
                    )
                    IconButton(onClick = {
                        val hasMic = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                            PackageManager.PERMISSION_GRANTED
                        if (!hasMic) return@IconButton
                        if (isListening) voiceController.cancel() else voiceController.start()
                    }) {
                        Icon(
                            if (isListening) Icons.Filled.Stop else Icons.Filled.Mic,
                            contentDescription = if (isListening) "Stop" else "Speak title"
                        )
                    }
                }
                OutlinedTextField(value = notes, onValueChange = { notes = it }, label = { Text("Notes (optional)") })
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    if (todoTitle.isNotBlank()) onSave(todoTitle.trim(), notes.ifBlank { null })
                }
            ) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } }
    )
}
