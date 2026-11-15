package com.digitalngai.mirror.location

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat

/**
 * Always-on tracking, Strava-style: no manual switch. Called on permission
 * grant, app start, and boot so the service just runs continuously as long
 * as location permission is held.
 */
object LocationTrackingStarter {
    fun startIfPermitted(context: Context) {
        val hasFine = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        val hasCoarse = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        if (!hasFine && !hasCoarse) return

        val intent = Intent(context, LocationTrackingService::class.java)
        ContextCompat.startForegroundService(context, intent)
    }
}
