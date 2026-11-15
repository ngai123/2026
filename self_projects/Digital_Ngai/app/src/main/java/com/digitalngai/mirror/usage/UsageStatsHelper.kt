package com.digitalngai.mirror.usage

import android.app.AppOpsManager
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Process
import android.provider.Settings

data class AppUsage(
    val packageName: String,
    val label: String,
    val foregroundMillis: Long
)

/**
 * Screen time is not a normal runtime permission -- Android requires the
 * user to flip it on manually in system Settings (Special app access ->
 * Usage access). This wraps that check/redirect plus the actual query.
 */
object UsageStatsHelper {

    fun hasUsageAccess(context: Context): Boolean {
        val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = appOps.unsafeCheckOpNoThrow(
            AppOpsManager.OPSTR_GET_USAGE_STATS,
            Process.myUid(),
            context.packageName
        )
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun openUsageAccessSettings(context: Context) {
        context.startActivity(
            Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }

    /** Per-app foreground time between [fromMillis, toMillis), sorted highest first. */
    fun usageBetween(context: Context, fromMillis: Long, toMillis: Long): List<AppUsage> {
        if (!hasUsageAccess(context)) return emptyList()

        val usm = context.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val stats = usm.queryAndAggregateUsageStats(fromMillis, toMillis)
        val pm = context.packageManager
        val selfPackage = context.packageName

        return stats.values
            .filter { it.totalTimeInForeground > 0 && it.packageName != selfPackage }
            .mapNotNull { usage ->
                val label = appLabel(pm, usage.packageName) ?: return@mapNotNull null
                AppUsage(usage.packageName, label, usage.totalTimeInForeground)
            }
            .sortedByDescending { it.foregroundMillis }
    }

    private fun appLabel(pm: PackageManager, packageName: String): String? = try {
        val info: ApplicationInfo = pm.getApplicationInfo(packageName, 0)
        // Skip apps with no launcher entry (system services etc.) -- not meaningful "screen time".
        if (pm.getLaunchIntentForPackage(packageName) == null) null
        else pm.getApplicationLabel(info).toString()
    } catch (_: PackageManager.NameNotFoundException) {
        null
    }
}
