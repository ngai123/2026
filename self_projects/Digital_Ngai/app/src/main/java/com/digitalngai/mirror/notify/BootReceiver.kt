package com.digitalngai.mirror.notify

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.digitalngai.mirror.location.LocationTrackingStarter
import com.digitalngai.mirror.work.CheckInWorker

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            CheckInWorker.schedule(context)
            LocationTrackingStarter.startIfPermitted(context)
        }
    }
}
