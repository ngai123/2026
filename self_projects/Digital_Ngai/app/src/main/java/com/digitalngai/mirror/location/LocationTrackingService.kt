package com.digitalngai.mirror.location

import android.app.Notification
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.digitalngai.mirror.DigitalNgaiApp
import com.digitalngai.mirror.MainActivity
import com.digitalngai.mirror.R
import com.digitalngai.mirror.data.local.LocationPing
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Foreground service that requests GPS-grade location updates and writes
 * each one straight to Room. High accuracy trades battery for precision --
 * this favors precision (Google Maps-like, ~3-10m outdoors) since the whole
 * point of the trail is knowing exactly where the user was, not roughly.
 */
class LocationTrackingService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var fusedClient: com.google.android.gms.location.FusedLocationProviderClient

    private val callback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            val location = result.lastLocation ?: return
            scope.launch {
                val repo = (application as DigitalNgaiApp).repository
                repo.logLocation(
                    LocationPing(
                        timestamp = System.currentTimeMillis(),
                        latitude = location.latitude,
                        longitude = location.longitude,
                        accuracyMeters = location.accuracy
                    )
                )
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        fusedClient = LocationServices.getFusedLocationProviderClient(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground()
        startLocationUpdates()
        return START_STICKY
    }

    private fun startForeground() {
        val openAppIntent = Intent(this, MainActivity::class.java)
        val pendingIntent = android.app.PendingIntent.getActivity(
            this, 0, openAppIntent,
            android.app.PendingIntent.FLAG_IMMUTABLE
        )
        val notification: Notification = NotificationCompat.Builder(this, DigitalNgaiApp.CHANNEL_LOCATION)
            .setContentTitle("Digital Ngai is logging your day")
            .setContentText("Tracking location in the background")
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun startLocationUpdates() {
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, INTERVAL_MS)
            .setMinUpdateIntervalMillis(INTERVAL_MS / 2)
            .setMinUpdateDistanceMeters(0f)
            .build()
        try {
            fusedClient.requestLocationUpdates(request, callback, mainLooper)
        } catch (_: SecurityException) {
            // Permission was revoked after the service started; stop cleanly.
            stopSelf()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        fusedClient.removeLocationUpdates(callback)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val NOTIFICATION_ID = 42
        private const val INTERVAL_MS = 2 * 60 * 1000L // 2 minutes -- tighter trail, still battery-reasonable
    }
}
