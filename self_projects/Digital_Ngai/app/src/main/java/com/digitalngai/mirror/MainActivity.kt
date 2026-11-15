package com.digitalngai.mirror

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarViewDay
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.EditNote
import androidx.compose.material.icons.filled.Map
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FabPosition
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.digitalngai.mirror.location.LocationTrackingStarter
import com.digitalngai.mirror.ui.AppViewModel
import com.digitalngai.mirror.ui.screens.JournalScreen
import com.digitalngai.mirror.ui.screens.MapScreen
import com.digitalngai.mirror.ui.screens.SettingsScreen
import com.digitalngai.mirror.ui.screens.TimelineScreen
import com.digitalngai.mirror.ui.screens.TodosScreen
import com.digitalngai.mirror.ui.theme.DigitalNgaiTheme
import com.digitalngai.mirror.voice.VoiceCaptureController
import com.digitalngai.mirror.voice.VoiceCaptureState
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private val viewModel: AppViewModel by viewModels { AppViewModel.factory(application) }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { LocationTrackingStarter.startIfPermitted(this) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        LocationTrackingStarter.startIfPermitted(this)
        requestRuntimePermissions()

        val openCheckIn = intent.getBooleanExtra(EXTRA_OPEN_CHECKIN, false)

        setContent {
            DigitalNgaiTheme {
                var showCheckInDialog by remember { mutableStateOf(openCheckIn) }
                MainScreen(viewModel)
                if (showCheckInDialog) {
                    CheckInDialog(
                        onDismiss = { showCheckInDialog = false },
                        onSave = { answer ->
                            viewModel.addTextJournalEntry(answer, promptText = "What are you doing right now?")
                            showCheckInDialog = false
                        }
                    )
                }
            }
        }
    }

    private fun requestRuntimePermissions() {
        val perms = mutableListOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.RECORD_AUDIO
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            perms += Manifest.permission.POST_NOTIFICATIONS
        }
        permissionLauncher.launch(perms.toTypedArray())
    }

    companion object {
        const val EXTRA_OPEN_CHECKIN = "open_checkin"
    }
}

@Composable
private fun MainScreen(viewModel: AppViewModel) {
    var selected by remember { mutableIntStateOf(0) }
    val tabs = listOf("Timeline", "Map", "Todos", "Journal", "Settings")
    val icons = listOf(
        Icons.Filled.CalendarViewDay,
        Icons.Filled.Map,
        Icons.Filled.CheckCircle,
        Icons.Filled.EditNote,
        Icons.Filled.Settings
    )

    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }
    var captureState by remember { mutableStateOf(VoiceCaptureState.IDLE) }

    val voiceController = remember {
        VoiceCaptureController(
            context = context,
            onState = { captureState = it },
            onResult = { transcript -> viewModel.handleVoiceTranscript(transcript) },
            onError = { message -> viewModel.voiceCaptureError(message) }
        )
    }
    DisposableEffect(Unit) { onDispose { voiceController.cancel() } }

    val captureMessage by viewModel.voiceCaptureMessage.collectAsState()
    LaunchedEffect(captureMessage) {
        captureMessage?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.clearVoiceCaptureMessage()
        }
    }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbarHostState) { Snackbar(it) } },
        floatingActionButtonPosition = FabPosition.Center,
        floatingActionButton = {
            FloatingActionButton(onClick = {
                val hasMic = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                    PackageManager.PERMISSION_GRANTED
                if (!hasMic) {
                    scope.launch { snackbarHostState.showSnackbar("Microphone permission is required.") }
                    return@FloatingActionButton
                }
                if (captureState == VoiceCaptureState.IDLE) voiceController.start() else voiceController.cancel()
            }) {
                Icon(
                    if (captureState == VoiceCaptureState.IDLE) Icons.Filled.Mic else Icons.Filled.Stop,
                    contentDescription = if (captureState == VoiceCaptureState.IDLE) "Talk to Digital Ngai" else "Stop listening"
                )
            }
        },
        bottomBar = {
            NavigationBar {
                tabs.forEachIndexed { index, label ->
                    NavigationBarItem(
                        selected = selected == index,
                        onClick = { selected = index },
                        icon = { Icon(icons[index], contentDescription = label) },
                        label = { Text(label) }
                    )
                }
            }
        }
    ) { padding ->
        androidx.compose.foundation.layout.Box(Modifier.fillMaxSize().padding(padding)) {
            when (selected) {
                0 -> TimelineScreen(viewModel)
                1 -> MapScreen(viewModel)
                2 -> TodosScreen(viewModel)
                3 -> JournalScreen(viewModel)
                4 -> SettingsScreen(viewModel)
            }
            if (captureState != VoiceCaptureState.IDLE) {
                Text(
                    if (captureState == VoiceCaptureState.LISTENING) "Listening..." else "Working on it...",
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(top = 12.dp)
                        .background(
                            androidx.compose.material3.MaterialTheme.colorScheme.primaryContainer,
                            RoundedCornerShape(50)
                        )
                        .padding(horizontal = 16.dp, vertical = 8.dp)
                )
            }
        }
    }
}

@Composable
private fun CheckInDialog(onDismiss: () -> Unit, onSave: (String) -> Unit) {
    var answer by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("What are you doing right now?") },
        text = {
            OutlinedTextField(value = answer, onValueChange = { answer = it }, label = { Text("Right now I'm...") })
        },
        confirmButton = {
            TextButton(onClick = { if (answer.isNotBlank()) onSave(answer.trim()) else onDismiss() }) { Text("Save") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Skip") } }
    )
}
