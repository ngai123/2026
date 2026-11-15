package com.digitalngai.mirror

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.digitalngai.mirror.data.Repository
import com.digitalngai.mirror.location.LocationTrackingStarter
import com.digitalngai.mirror.work.CheckInWorker
import org.osmdroid.config.Configuration

class DigitalNgaiApp : Application() {

    lateinit var repository: Repository
        private set

    override fun onCreate() {
        super.onCreate()
        repository = Repository(this)
        createNotificationChannels()
        CheckInWorker.schedule(this)
        LocationTrackingStarter.startIfPermitted(this)
        configureOsmdroid()
    }

    private fun configureOsmdroid() {
        Configuration.getInstance().apply {
            userAgentValue = packageName
            osmdroidBasePath = getDir("osmdroid", MODE_PRIVATE)
            osmdroidTileCache = getDir("osmdroid_tiles", MODE_PRIVATE)
        }
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_CHECKIN,
                "Check-ins",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply { description = "Periodic prompts asking what you're doing" }
        )
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_LOCATION,
                "Location tracking",
                NotificationManager.IMPORTANCE_MIN
            ).apply { description = "Ongoing background location logging" }
        )
    }

    companion object {
        const val CHANNEL_CHECKIN = "checkin"
        const val CHANNEL_LOCATION = "location"
    }
}
