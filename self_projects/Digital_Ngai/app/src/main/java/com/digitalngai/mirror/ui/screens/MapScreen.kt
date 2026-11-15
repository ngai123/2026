package com.digitalngai.mirror.ui.screens

import android.graphics.Color
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.digitalngai.mirror.ui.AppViewModel
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polyline

/**
 * Strava-style trail: everywhere the location service has logged in the
 * last 24h, drawn as a line over OpenStreetMap tiles. No API key needed.
 */
@Composable
fun MapScreen(viewModel: AppViewModel) {
    val locations by viewModel.recentLocations.collectAsState()
    val context = LocalContext.current

    val mapView = remember {
        MapView(context).apply {
            setTileSource(TileSourceFactory.MAPNIK)
            setMultiTouchControls(true)
            controller.setZoom(14.0)
        }
    }
    DisposableEffect(Unit) { onDispose { mapView.onDetach() } }

    Box(Modifier.fillMaxSize()) {
        AndroidView(modifier = Modifier.fillMaxSize(), factory = { mapView }) { view ->
            view.overlays.clear()
            val points = locations.sortedBy { it.timestamp }.map { GeoPoint(it.latitude, it.longitude) }
            if (points.isNotEmpty()) {
                view.overlays.add(
                    Polyline().apply {
                        setPoints(points)
                        outlinePaint.color = Color.parseColor("#7C4DFF")
                        outlinePaint.strokeWidth = 8f
                    }
                )
                view.overlays.add(
                    Marker(view).apply {
                        position = points.last()
                        setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
                        title = "Now"
                    }
                )
                view.controller.setCenter(points.last())
            }
            view.invalidate()
        }

        if (locations.isEmpty()) {
            Text(
                "No location logged yet -- tracking runs continuously in the background, check back shortly.",
                modifier = Modifier
                    .align(Alignment.TopCenter)
                    .padding(12.dp)
                    .background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(12.dp))
                    .padding(12.dp)
            )
        }
    }
}
