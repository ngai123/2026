package com.digitalngai.mirror.work

import android.Manifest
import android.app.PendingIntent
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.digitalngai.mirror.DigitalNgaiApp
import com.digitalngai.mirror.MainActivity
import com.digitalngai.mirror.R
import java.util.concurrent.TimeUnit

/**
 * Periodically nudges the user with "what are you doing right now?" so the
 * journal has more than passive location/todo data -- the actual texture of
 * the day, in the user's own words.
 */
class CheckInWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        postCheckInNotification(applicationContext)
        return Result.success()
    }

    companion object {
        private const val WORK_NAME = "periodic_checkin"
        private const val NOTIFICATION_ID = 100

        fun schedule(context: Context) {
            val request = PeriodicWorkRequestBuilder<CheckInWorker>(3, TimeUnit.HOURS)
                .setConstraints(Constraints.Builder().build())
                .build()
            WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                WORK_NAME,
                ExistingPeriodicWorkPolicy.KEEP,
                request
            )
        }

        fun postCheckInNotification(context: Context) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                ActivityCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                return
            }

            val openIntent = android.content.Intent(context, MainActivity::class.java).apply {
                putExtra(MainActivity.EXTRA_OPEN_CHECKIN, true)
            }
            val pendingIntent = PendingIntent.getActivity(
                context, 0, openIntent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )

            val notification = NotificationCompat.Builder(context, DigitalNgaiApp.CHANNEL_CHECKIN)
                .setSmallIcon(R.drawable.ic_launcher_foreground)
                .setContentTitle("What are you doing right now?")
                .setContentText("Tap to log it in Digital Ngai")
                .setPriority(NotificationCompat.PRIORITY_DEFAULT)
                .setAutoCancel(true)
                .setContentIntent(pendingIntent)
                .build()

            NotificationManagerCompat.from(context).notify(NOTIFICATION_ID, notification)
        }
    }
}
