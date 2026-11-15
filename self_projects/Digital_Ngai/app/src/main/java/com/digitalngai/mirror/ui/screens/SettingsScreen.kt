package com.digitalngai.mirror.ui.screens

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.digitalngai.mirror.ui.AppViewModel
import com.digitalngai.mirror.usage.AppUsage
import com.digitalngai.mirror.usage.UsageStatsHelper
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.concurrent.TimeUnit

@Composable
fun SettingsScreen(viewModel: AppViewModel) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var exportStatus by remember { mutableStateOf<String?>(null) }

    val hasLocationPermission = ContextCompat.checkSelfPermission(
        context, Manifest.permission.ACCESS_FINE_LOCATION
    ) == PackageManager.PERMISSION_GRANTED || ContextCompat.checkSelfPermission(
        context, Manifest.permission.ACCESS_COARSE_LOCATION
    ) == PackageManager.PERMISSION_GRANTED

    var hasUsageAccess by remember { mutableStateOf(UsageStatsHelper.hasUsageAccess(context)) }
    var todayUsage by remember { mutableStateOf<List<AppUsage>>(emptyList()) }

    LaunchedEffect(hasUsageAccess) {
        while (hasUsageAccess) {
            val now = System.currentTimeMillis()
            todayUsage = UsageStatsHelper.usageBetween(context, now - TimeUnit.HOURS.toMillis(24), now).take(8)
            delay(30_000)
        }
    }

    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp)) {
        Text("Location tracking", style = MaterialTheme.typography.titleMedium)
        Text(
            if (hasLocationPermission) "Always on — runs continuously in the background, like Strava."
            else "Waiting on location permission. Grant it from the system prompt or in phone Settings → Apps → Digital Ngai → Permissions.",
            style = MaterialTheme.typography.bodySmall
        )

        Spacer(Modifier.padding(8.dp))
        Text("Screen time", style = MaterialTheme.typography.titleMedium)
        if (hasUsageAccess) {
            Text(
                "Access granted. Updates automatically every 30s. Included in the AI export.",
                style = MaterialTheme.typography.bodySmall
            )

            todayUsage.forEach { usage ->
                val minutes = TimeUnit.MILLISECONDS.toMinutes(usage.foregroundMillis)
                Text("${usage.label} — ${minutes / 60}h ${minutes % 60}m", style = MaterialTheme.typography.bodySmall)
            }
        } else {
            Text(
                "Not granted yet. Android requires this to be turned on manually — it's a " +
                    "sensitive permission the system won't show a normal popup for.",
                style = MaterialTheme.typography.bodySmall
            )
            Button(onClick = {
                UsageStatsHelper.openUsageAccessSettings(context)
            }) { Text("Open Settings to grant access") }
            Button(onClick = { hasUsageAccess = UsageStatsHelper.hasUsageAccess(context) }) {
                Text("I granted it, check again")
            }
        }

        Spacer(Modifier.padding(8.dp))
        Text("Export for AI", style = MaterialTheme.typography.titleMedium)
        Text(
            "Bundles your recent location, todos, journal entries, and screen time into a JSON " +
                "file you can share with an AI assistant so it has real context about your day.",
            style = MaterialTheme.typography.bodySmall
        )
        Button(onClick = {
            scope.launch {
                val file = viewModel.exportLastDays(7)
                exportStatus = "Saved to ${file.absolutePath}"
                val shareIntent = Intent(Intent.ACTION_SEND).apply {
                    type = "application/json"
                    putExtra(Intent.EXTRA_STREAM, viewModel.shareUri(file))
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
                context.startActivity(Intent.createChooser(shareIntent, "Share export"))
            }
        }) { Text("Export last 7 days") }

        exportStatus?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
    }
}
