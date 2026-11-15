"""
dashboard_3d_recon.py
=====================
Backup of the 3D Recon view previously served at /3d from dashboard.py.
Kept for reference only — not wired into the running app.
"""

# ── 3D City Recon Page ─────────────────────────────────────────────────────────

_HTML_3D = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>3D Recon — Metro Manila City View</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; overflow: hidden; background: #050a14; color: #f0f4f8; font-family: 'Inter', sans-serif; }

#canvas-container {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 0;
}
canvas { display: block; width: 100%; height: 100%; }

/* ── HUD Overlay ── */
#hud {
  position: fixed; top: 0; left: 0; right: 0; z-index: 100;
  padding: 16px 24px;
  display: flex; justify-content: space-between; align-items: flex-start;
  pointer-events: none;
}
#hud > * { pointer-events: auto; }

#hud-left {
  display: flex; flex-direction: column; gap: 8px;
}

#hud-title {
  font-family: 'Outfit', sans-serif;
  font-size: 18px; font-weight: 800;
  text-transform: uppercase; letter-spacing: 0.05em;
  background: linear-gradient(135deg, #f0f4f8, #0088ff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}

#hud-subtitle {
  font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: 0.1em;
}

#hud-controls {
  display: flex; gap: 8px; margin-top: 8px;
}

.hud-btn {
  background: rgba(13, 22, 40, 0.8);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.1);
  color: #94a3b8; padding: 8px 16px; border-radius: 8px;
  font-size: 11px; font-weight: 700; cursor: pointer;
  text-transform: uppercase; letter-spacing: 0.02em;
  transition: all 0.2s;
}
.hud-btn:hover { background: #0088ff; color: #050a14; border-color: #0088ff; }
.hud-btn.active { background: rgba(0,136,255,0.2); color: #0088ff; border-color: #0088ff; }
.hud-btn.danger { color: #ff2a6d; border-color: rgba(255,42,109,0.3); }
.hud-btn.danger:hover { background: #ff2a6d; color: #fff; }

#hud-right {
  display: flex; flex-direction: column; gap: 6px; align-items: flex-end;
}

#hud-stats {
  display: flex; gap: 8px;
}

.hud-stat {
  background: rgba(13, 22, 40, 0.8);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px; padding: 6px 12px;
  display: flex; flex-direction: column; min-width: 80px;
}
.hud-stat-label { font-size: 9px; color: #64748b; text-transform: uppercase; font-weight: 600; }
.hud-stat-value { font-size: 13px; font-weight: 700; font-family: 'JetBrains Mono'; color: #0088ff; }

/* ── Help Panel ── */
#help-panel {
  position: fixed; bottom: 16px; left: 16px; z-index: 100;
  background: rgba(13, 22, 40, 0.85);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px; padding: 14px 18px;
  font-size: 12px; color: #94a3b8;
  line-height: 1.8;
  pointer-events: none;
}
#help-panel .key {
  display: inline-block; background: rgba(0,136,255,0.15);
  border: 1px solid rgba(0,136,255,0.3);
  color: #0088ff; border-radius: 4px;
  padding: 1px 6px; font-family: 'JetBrains Mono';
  font-size: 11px; font-weight: 600; margin-right: 4px;
}

/* ── Path Info ── */
#path-info {
  position: fixed; bottom: 16px; right: 16px; z-index: 100;
  background: rgba(13, 22, 40, 0.85);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(0,136,255,0.2);
  border-radius: 10px; padding: 14px 18px;
  font-size: 12px; color: #94a3b8;
  min-width: 200px;
  display: none;
}
#path-info.visible { display: block; }

/* ── Loading Screen ── */
#loading-screen {
  position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 1000;
  background: #050a14;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 20px;
}
#loading-screen h2 {
  font-family: 'Outfit', sans-serif; font-size: 22px; font-weight: 800;
  background: linear-gradient(135deg, #f0f4f8, #0088ff);
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
#loading-bar-wrap {
  width: 300px; height: 4px; background: rgba(255,255,255,0.05); border-radius: 2px; overflow: hidden;
}
#loading-bar {
  height: 100%; width: 0%; background: linear-gradient(90deg, #00ff9f, #0088ff);
  box-shadow: 0 0 8px rgba(0,255,159,0.3); transition: width 0.3s;
}
#loading-status { font-size: 12px; color: #64748b; }

/* ── Scroll container for flythrough mode ── */
#scroll-container {
  display: none;
  position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 50;
  overflow-y: auto;
}
#scroll-spacer { height: 8000px; pointer-events: none; }

/* ── Crosshair ── */
#crosshair {
  position: fixed; top: 50%; left: 50%;
  width: 20px; height: 20px;
  transform: translate(-50%, -50%);
  z-index: 90; pointer-events: none; display: none;
}
#crosshair::before, #crosshair::after {
  content: ''; position: absolute; background: rgba(0,136,255,0.6);
}
#crosshair::before { top: 0; left: 50%; width: 1px; height: 100%; transform: translateX(-50%); }
#crosshair::after { top: 50%; left: 0; width: 100%; height: 1px; transform: translateY(-50%); }

/* ── Survivor/Drone markers in 3D ── */
.marker-3d {
  position: absolute; pointer-events: none;
  font-size: 10px; font-weight: 700;
  font-family: 'JetBrains Mono';
  text-align: center;
  text-shadow: 0 0 8px rgba(0,0,0,0.8);
  transform: translate(-50%, -50%);
}

/* ── Toast notifications ── */
#toast {
  position: fixed; top: 80px; left: 50%;
  transform: translateX(-50%);
  z-index: 200;
  background: rgba(0,136,255,0.15);
  border: 1px solid rgba(0,136,255,0.4);
  color: #0088ff; border-radius: 8px;
  padding: 8px 20px; font-size: 12px; font-weight: 600;
  opacity: 0; transition: opacity 0.3s;
  pointer-events: none;
}
#toast.show { opacity: 1; }
</style>
</head>
<body>

<div id="loading-screen">
  <h2>3D RECON — METRO MANILA</h2>
  <div id="loading-bar-wrap"><div id="loading-bar"></div></div>
  <div id="loading-status">Initializing...</div>
</div>

<div id="canvas-container"></div>

<div id="hud">
  <div id="hud-left">
    <div id="hud-title">3D Recon View</div>
    <div id="hud-subtitle">Metro Manila Disaster Zone</div>
    <div id="hud-controls">
      <button class="hud-btn active" id="btn-edit" onclick="setMode('edit')">Edit Path</button>
      <button class="hud-btn" id="btn-fly" onclick="setMode('fly')">Flythrough</button>
      <button class="hud-btn" id="btn-orbit" onclick="setMode('orbit')">Free Orbit</button>
      <a class="hud-btn" href="/">Dashboard</a>
    </div>
  </div>
  <div id="hud-right">
    <div id="hud-stats">
      <div class="hud-stat">
        <span class="hud-stat-label">Buildings</span>
        <span class="hud-stat-value" id="stat-buildings">—</span>
      </div>
      <div class="hud-stat">
        <span class="hud-stat-label">Waypoints</span>
        <span class="hud-stat-value" id="stat-waypoints">0</span>
      </div>
      <div class="hud-stat">
        <span class="hud-stat-label">Survivors</span>
        <span class="hud-stat-value" id="stat-survivors">—</span>
      </div>
      <div class="hud-stat">
        <span class="hud-stat-label">Drones</span>
        <span class="hud-stat-value" id="stat-drones">—</span>
      </div>
    </div>
  </div>
</div>

<div id="help-panel">
  <span class="key">Click</span> Add waypoint
  <br><span class="key">S</span> Save path
  <br><span class="key">Z</span> Undo
  <br><span class="key">X</span> Redo
  <br><span class="key">R</span> Reset path
  <br><span class="key">Scroll</span> Zoom &nbsp;|&nbsp; <span class="key">Drag</span> Rotate
</div>

<div id="path-info" class="visible">
  <div style="font-weight:700; color:#0088ff; margin-bottom:6px;">PATH</div>
  <div id="path-detail">No waypoints yet</div>
</div>

<div id="scroll-container">
  <div id="scroll-spacer"></div>
</div>

<div id="crosshair"></div>
<div id="toast"></div>

<!-- Three.js + OrbitControls + Sky + PostProcessing from CDN -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/utils/BufferGeometryUtils.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/objects/Sky.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/shaders/CopyShader.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/shaders/LuminosityHighPassShader.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/shaders/FXAAShader.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/EffectComposer.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/RenderPass.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/ShaderPass.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/UnrealBloomPass.js"></script>

<script>
'use strict';

// ═══════════════════════════════════════════════════════════════════════════════
// GLOBALS
// ═══════════════════════════════════════════════════════════════════════════════

const CENTER = { lng: 120.980, lat: 14.590 };
const METER_PER_DEG_LAT = 111320;
const METER_PER_DEG_LNG = 111320 * Math.cos(CENTER.lat * Math.PI / 180);
const SCALE = 1;  // 1 unit = 1 meter
const LEVEL_HEIGHT = 3.5;  // meters per floor

let scene, camera, renderer, controls, composer;
let sky, sunLight, hemiLight;
const sunParams = { elevation: 42, azimuth: 135 };  // Manila mid-morning
let groundMesh, buildingMesh;
let mode = 'edit';   // 'edit' | 'fly' | 'orbit'
let raycaster, mouse;

// Path system
let pathPoints = [];
let pathUndoStack = [];
let pathSphereMeshes = [];
let pathLineMesh = null;

// Rescue data
let rescueMarkers = { survivors: [], drones: [] };
let survivorMeshes = [], droneMeshes = [];
let floodMeshes = [];
let baseGroup = null, sectorGroup = null;

// ── Simulation constants mirroring metro_manila_rescue.py ──────────────────
// Meters per kilometre — used to convert km-radii into local scene units.
const VISION_RADIUS_M = 100;       // 0.1 km = 100 m drone scan radius
const BASE_CENTER_GEO = { lng: 120.980, lat: 14.590 };
const BASE_STATIONS = {
  "Roxas Blvd Hub":    { lng: 120.978, lat: 14.575, colour: 0x00e8ff },
  "Intramuros Base":   { lng: 120.975, lat: 14.589, colour: 0xffaa00 },
  "UST Field Station": { lng: 120.989, lat: 14.610, colour: 0x7a88ff },
};
const TEAM_SECTORS = [
  { id: "S1", start:   0, end:  72, colour: 0xff6600, name: "Alpha"   },
  { id: "S2", start:  72, end: 144, colour: 0xff2222, name: "Bravo"   },
  { id: "S3", start: 144, end: 216, colour: 0x2244ff, name: "Charlie" },
  { id: "S4", start: 216, end: 288, colour: 0x22bb22, name: "Delta"   },
  { id: "S5", start: 288, end: 360, colour: 0xbb22bb, name: "Echo"    },
];
const SECTOR_RADIUS_M = 1500;      // 1.5 km — outer ring from simulation

// Colour palette for drone roles / bases
const DRONE_COLOURS = {
  OUTER:  0xff2a6d,
  MIDDLE: 0x0088ff,
  INNER:  0x00ff9f,
  CMD:    0xffd700,
};

// ═══════════════════════════════════════════════════════════════════════════════
// COORDINATE CONVERSION
// ═══════════════════════════════════════════════════════════════════════════════

function geoToLocal(lng, lat) {
  const x = (lng - CENTER.lng) * METER_PER_DEG_LNG * SCALE;
  const z = -(lat - CENTER.lat) * METER_PER_DEG_LAT * SCALE;
  return { x, z };
}

function localToGeo(x, z) {
  const lng = x / (METER_PER_DEG_LNG * SCALE) + CENTER.lng;
  const lat = -z / (METER_PER_DEG_LAT * SCALE) + CENTER.lat;
  return { lng, lat };
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENE INITIALIZATION
// ═══════════════════════════════════════════════════════════════════════════════

function initScene() {
  scene = new THREE.Scene();

  // Camera — wider far plane for the atmospheric sky dome
  camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 1, 60000);
  camera.position.set(600, 900, 1400);
  camera.lookAt(0, 0, 0);

  // Renderer (PBR, ACES tonemapping, physically correct lights)
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputEncoding = THREE.sRGBEncoding;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.9;
  renderer.physicallyCorrectLights = false;
  document.getElementById('canvas-container').appendChild(renderer.domElement);

  // Orbit Controls
  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;
  controls.maxPolarAngle = Math.PI / 2.05;
  controls.minDistance = 50;
  controls.maxDistance = 8000;
  controls.target.set(0, 0, 0);

  // ── Atmospheric sky (Preetham/Hosek via three.js Sky) ─────────────────────
  sky = new THREE.Sky();
  sky.scale.setScalar(50000);
  const u = sky.material.uniforms;
  u['turbidity'].value = 6;
  u['rayleigh'].value = 1.8;
  u['mieCoefficient'].value = 0.005;
  u['mieDirectionalG'].value = 0.8;
  scene.add(sky);

  // Sun direction vector (derived from elevation/azimuth)
  const sunVec = new THREE.Vector3();
  const phi = THREE.MathUtils.degToRad(90 - sunParams.elevation);
  const theta = THREE.MathUtils.degToRad(sunParams.azimuth);
  sunVec.setFromSphericalCoords(1, phi, theta);
  u['sunPosition'].value.copy(sunVec);

  // Volumetric haze tinted to atmosphere — pulls distant buildings into the skyline
  scene.fog = new THREE.Fog(0xbfd4e6, 1800, 14000);

  // ── Lights (match sun direction) ──────────────────────────────────────────
  sunLight = new THREE.DirectionalLight(0xfff2d6, 1.4);
  sunLight.position.copy(sunVec).multiplyScalar(3000);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(2048, 2048);
  sunLight.shadow.camera.near = 100;
  sunLight.shadow.camera.far = 6000;
  sunLight.shadow.camera.left = -2500;
  sunLight.shadow.camera.right = 2500;
  sunLight.shadow.camera.top = 2500;
  sunLight.shadow.camera.bottom = -2500;
  sunLight.shadow.bias = -0.0003;
  sunLight.shadow.normalBias = 0.8;
  scene.add(sunLight);

  hemiLight = new THREE.HemisphereLight(0xbfdcff, 0x4a3a2a, 0.55);
  scene.add(hemiLight);

  // Subtle fill from opposite side (simulates sky bounce in shaded alleys)
  const fillLight = new THREE.DirectionalLight(0x88aacc, 0.25);
  fillLight.position.set(-sunVec.x, Math.max(0.3, sunVec.y * 0.5), -sunVec.z).multiplyScalar(1500);
  scene.add(fillLight);

  // ── Ground (receives satellite texture tiles later) ───────────────────────
  // A flat base-colour plane in case tiles fail to load.
  const groundGeo = new THREE.PlaneGeometry(12000, 12000);
  const groundMat = new THREE.MeshStandardMaterial({
    color: 0x4a5c42,   // warm earth / urban average
    roughness: 0.95,
    metalness: 0.0,
  });
  groundMesh = new THREE.Mesh(groundGeo, groundMat);
  groundMesh.rotation.x = -Math.PI / 2;
  groundMesh.position.y = -0.2;
  groundMesh.receiveShadow = true;
  scene.add(groundMesh);

  // Raycaster
  raycaster = new THREE.Raycaster();
  mouse = new THREE.Vector2();

  // Resize
  window.addEventListener('resize', onResize);
}

function onResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  if (composer) composer.setSize(window.innerWidth, window.innerHeight);
}

// ═══════════════════════════════════════════════════════════════════════════════
// POST-PROCESSING (bloom for glowing markers, FXAA, tone-mapped render)
// ═══════════════════════════════════════════════════════════════════════════════

function setupPostProcessing() {
  composer = new THREE.EffectComposer(renderer);
  composer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  composer.setSize(window.innerWidth, window.innerHeight);

  const renderPass = new THREE.RenderPass(scene, camera);
  composer.addPass(renderPass);

  const bloomPass = new THREE.UnrealBloomPass(
    new THREE.Vector2(window.innerWidth, window.innerHeight),
    0.45,   // strength
    0.6,    // radius
    0.92    // threshold — only very bright pixels bloom (markers, sun glints)
  );
  composer.addPass(bloomPass);

  // FXAA as a final pass to smooth jaggies after bloom
  const fxaa = new THREE.ShaderPass(THREE.FXAAShader);
  const pr = renderer.getPixelRatio();
  fxaa.material.uniforms['resolution'].value.set(
    1 / (window.innerWidth * pr),
    1 / (window.innerHeight * pr)
  );
  composer.addPass(fxaa);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SATELLITE IMAGERY (Esri World Imagery XYZ tiles — no token required)
// ═══════════════════════════════════════════════════════════════════════════════

function lonLatToTile(lon, lat, z) {
  const n = Math.pow(2, z);
  const x = Math.floor((lon + 180) / 360 * n);
  const latRad = lat * Math.PI / 180;
  const y = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);
  return { x, y };
}

function tileToLonLat(x, y, z) {
  const n = Math.pow(2, z);
  const lon = x / n * 360 - 180;
  const latRad = Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n)));
  const lat = latRad * 180 / Math.PI;
  return { lon, lat };
}

async function loadSatelliteTiles() {
  setLoadingStatus('Loading satellite imagery...', 20);

  const Z = 15;                       // ~1.2 km per tile at Manila latitude
  const radiusTiles = 4;              // 9x9 = 81 tiles covering ~10km
  const center = lonLatToTile(CENTER.lng, CENTER.lat, Z);

  const loader = new THREE.TextureLoader();
  loader.crossOrigin = 'anonymous';

  const tilePromises = [];
  for (let dx = -radiusTiles; dx <= radiusTiles; dx++) {
    for (let dy = -radiusTiles; dy <= radiusTiles; dy++) {
      const tx = center.x + dx;
      const ty = center.y + dy;
      const url = `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${Z}/${ty}/${tx}`;
      const nw = tileToLonLat(tx, ty, Z);
      const se = tileToLonLat(tx + 1, ty + 1, Z);
      const a = geoToLocal(nw.lon, nw.lat);
      const b = geoToLocal(se.lon, se.lat);
      const w = Math.abs(b.x - a.x);
      const h = Math.abs(b.z - a.z);
      const cx = (a.x + b.x) / 2;
      const cz = (a.z + b.z) / 2;

      tilePromises.push(new Promise(resolve => {
        loader.load(url, (tex) => {
          tex.encoding = THREE.sRGBEncoding;
          tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
          const mat = new THREE.MeshStandardMaterial({
            map: tex,
            roughness: 0.95,
            metalness: 0.0,
          });
          const geo = new THREE.PlaneGeometry(w, h);
          const mesh = new THREE.Mesh(geo, mat);
          mesh.rotation.x = -Math.PI / 2;
          mesh.position.set(cx, 0, cz);
          mesh.receiveShadow = true;
          scene.add(mesh);
          resolve(true);
        }, undefined, () => resolve(false));
      }));
    }
  }

  await Promise.all(tilePromises);
  // Sink the fallback ground beneath the tiles so it only shows past the edge.
  groundMesh.position.y = -0.5;
  setLoadingStatus('Satellite imagery loaded', 30);
}

// ═══════════════════════════════════════════════════════════════════════════════
// OSM BUILDING LOADING (Overpass API)
// ═══════════════════════════════════════════════════════════════════════════════

async function fetchBuildings() {
  setLoadingStatus('Querying OpenStreetMap...', 35);

  const bbox = `${CENTER.lat - 0.025},${CENTER.lng - 0.025},${CENTER.lat + 0.025},${CENTER.lng + 0.025}`;
  // Fetch buildings AND building:part (for complex buildings with multiple extrusions)
  const query = `
    [out:json][timeout:90];
    (
      way["building"](${bbox});
      way["building:part"](${bbox});
      relation["building"](${bbox});
    );
    out body;
    >;
    out skel qt;
  `;

  const url = 'https://overpass-api.de/api/interpreter';
  const response = await fetch(url, {
    method: 'POST',
    body: 'data=' + encodeURIComponent(query),
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });

  setLoadingStatus('Parsing building data...', 45);
  const data = await response.json();
  return data.elements;
}

// Per-type defaults informed by OSM Simple3DBuildings conventions.
// Values are { floors, extraHeightPerFloor } used only when no explicit height tag exists.
const BUILDING_TYPE_DEFAULTS = {
  house:         { floors: 1, floor: 3.0 },
  residential:   { floors: 3, floor: 3.0 },
  apartments:    { floors: 5, floor: 3.0 },
  detached:      { floors: 2, floor: 3.2 },
  terrace:       { floors: 2, floor: 3.0 },
  commercial:    { floors: 3, floor: 3.8 },
  retail:        { floors: 2, floor: 4.0 },
  office:        { floors: 6, floor: 3.5 },
  industrial:    { floors: 1, floor: 6.0 },
  warehouse:     { floors: 1, floor: 7.0 },
  hospital:      { floors: 4, floor: 3.8 },
  school:        { floors: 3, floor: 3.8 },
  university:    { floors: 4, floor: 3.8 },
  hotel:         { floors: 8, floor: 3.3 },
  church:        { floors: 1, floor: 12.0 },
  cathedral:     { floors: 1, floor: 22.0 },
  temple:        { floors: 1, floor: 10.0 },
  mosque:        { floors: 1, floor: 12.0 },
  skyscraper:    { floors: 25, floor: 3.5 },
  garage:        { floors: 1, floor: 2.8 },
  roof:          { floors: 0, floor: 3.0 },
  shed:          { floors: 1, floor: 2.5 },
  kiosk:         { floors: 1, floor: 2.5 },
};

// Colour palette keyed on building type — nudges the scene away from a uniform grey mass.
const BUILDING_TYPE_COLORS = {
  house:        [0xe8d9b6, 0xd4b483, 0xb07d62],
  residential:  [0xd4c4a8, 0xc7a878, 0xa68a6b],
  apartments:   [0xc9b896, 0xb8a274, 0x9e8560],
  commercial:   [0xd8dde0, 0xbfc4c8, 0xa8adb2],
  retail:       [0xe6d4b8, 0xd4b88a, 0xc89a6e],
  office:       [0xb8c8d4, 0x9cb0c0, 0x7d95a8],
  industrial:   [0xa89f94, 0x918778, 0x7a6f60],
  warehouse:    [0x9e948a, 0x887e72, 0x70665c],
  hospital:     [0xe8ecef, 0xd4dbe0, 0xbfc7cc],
  school:       [0xd4b88a, 0xc19d6b, 0xa8824f],
  church:       [0xcbbfa0, 0xb0a383, 0x8e826a],
  skyscraper:   [0xa8b8c8, 0x8a9cb0, 0x6d8096],
  default:      [0xc9bda5, 0xb0a388, 0x968870],
};

function parseHeight(tags) {
  // Try explicit height tags first (OSM convention: meters, may include units).
  const rawHeight = tags['height'] || tags['building:height'];
  if (rawHeight) {
    const m = String(rawHeight).match(/([\d.]+)/);
    if (m) return { height: parseFloat(m[1]), explicit: true };
  }
  // Fall back to level count * floor height.
  const levels = parseInt(tags['building:levels']);
  if (levels) {
    const bt = tags.building || tags['building:part'];
    const def = BUILDING_TYPE_DEFAULTS[bt] || { floor: 3.3 };
    return { height: levels * def.floor, explicit: false };
  }
  return null;
}

function parseMinHeight(tags) {
  const raw = tags['min_height'] || tags['building:min_height'];
  if (raw) {
    const m = String(raw).match(/([\d.]+)/);
    if (m) return parseFloat(m[1]);
  }
  const minLevel = parseInt(tags['building:min_level']);
  if (minLevel) return minLevel * 3.3;
  return 0;
}

function defaultHeightForType(type) {
  const def = BUILDING_TYPE_DEFAULTS[type] || { floors: 2, floor: 3.3 };
  // Add slight randomness so a row of houses doesn't pancake flat.
  const jitter = 0.8 + Math.random() * 0.4;
  return Math.max(3.0, def.floors * def.floor * jitter);
}

function parseBuildings(elements) {
  setLoadingStatus('Processing geometry...', 50);

  // Index nodes by ID
  const nodes = {};
  for (const el of elements) {
    if (el.type === 'node') {
      nodes[el.id] = { lng: el.lon, lat: el.lat };
    }
  }

  const buildings = [];
  for (const el of elements) {
    if (el.type !== 'way' || !el.tags) continue;
    if (!el.tags.building && !el.tags['building:part']) continue;

    const coords = [];
    for (const nid of el.nodes) {
      if (nodes[nid]) coords.push(nodes[nid]);
    }
    if (coords.length < 3) continue;

    const type = el.tags.building || el.tags['building:part'] || 'yes';
    const parsedH = parseHeight(el.tags);
    const height = parsedH ? parsedH.height : defaultHeightForType(type);
    const minHeight = parseMinHeight(el.tags);

    if (height - minHeight <= 0.5) continue;

    // Colour preference: OSM building:colour tag > type palette > default.
    let colour = null;
    const colourTag = el.tags['building:colour'] || el.tags['building:color'];
    if (colourTag) {
      const c = parseCssColour(colourTag);
      if (c !== null) colour = c;
    }
    if (colour === null) {
      const palette = BUILDING_TYPE_COLORS[type] || BUILDING_TYPE_COLORS.default;
      colour = palette[Math.floor(Math.random() * palette.length)];
    }

    buildings.push({ coords, height, minHeight, type, colour, tags: el.tags });
  }

  return buildings;
}

function parseCssColour(s) {
  s = String(s).trim().toLowerCase();
  if (s.startsWith('#')) {
    const hex = s.slice(1);
    if (hex.length === 6) return parseInt(hex, 16);
    if (hex.length === 3) {
      const r = parseInt(hex[0] + hex[0], 16);
      const g = parseInt(hex[1] + hex[1], 16);
      const b = parseInt(hex[2] + hex[2], 16);
      return (r << 16) | (g << 8) | b;
    }
  }
  const named = {
    white: 0xf5f5f0, beige: 0xe8d9b6, cream: 0xefe4c8, yellow: 0xe8d080,
    red: 0xb84030, brown: 0x8a6042, grey: 0xa8a8a8, gray: 0xa8a8a8,
    black: 0x2a2a2a, blue: 0x7596b0, green: 0x7a9d75,
  };
  return named[s] !== undefined ? named[s] : null;
}

function createBuildingMeshes(buildings) {
  setLoadingStatus('Extruding 3D buildings...', 65);

  const wallGeos = [];
  const roofGeos = [];
  let count = 0;

  const cTmp = new THREE.Color();

  for (const bld of buildings) {
    const pts = bld.coords.map(c => geoToLocal(c.lng, c.lat));
    if (pts.length < 3) continue;

    const shape = new THREE.Shape();
    shape.moveTo(pts[0].x, pts[0].z);
    for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i].x, pts[i].z);
    shape.lineTo(pts[0].x, pts[0].z);

    const height = bld.height;
    const baseHeight = bld.minHeight || 0;
    if (height - baseHeight <= 0.5) continue;

    try {
      const span = height - baseHeight;
      const geo = new THREE.ExtrudeGeometry(shape, {
        steps: 1,
        depth: span,
        bevelEnabled: false,
      });
      // Rotate so extrusion axis is +Y, then clamp bottom to baseHeight regardless
      // of whether ExtrudeGeometry output spans [0, span] or [-span, 0].
      geo.rotateX(-Math.PI / 2);
      geo.computeBoundingBox();
      const minY = geo.boundingBox.min.y;
      geo.translate(0, baseHeight - minY, 0);

      // Bake per-building colour into vertex colours so we can still merge everything.
      // Slight top-vs-bottom gradient for subtle AO feel and floor banding for tall blocks.
      cTmp.setHex(bld.colour);
      const positions = geo.getAttribute('position');
      const colours = new Float32Array(positions.count * 3);
      for (let i = 0; i < positions.count; i++) {
        const y = positions.getY(i);
        // Subtle darkening near ground (fake contact-shadow) and lighter at top
        const verticalT = Math.min((y - baseHeight) / Math.max(1, height - baseHeight), 1);
        const shade = 0.82 + verticalT * 0.22;
        // Per-floor banding — faint horizontal lines every ~3.3m for taller buildings
        const floorT = Math.sin((y / 3.3) * Math.PI * 2) * 0.04;
        colours[i * 3]     = cTmp.r * (shade + floorT);
        colours[i * 3 + 1] = cTmp.g * (shade + floorT);
        colours[i * 3 + 2] = cTmp.b * (shade + floorT);
      }
      geo.setAttribute('color', new THREE.BufferAttribute(colours, 3));
      wallGeos.push(geo);

      // Flat roof cap — distinct dark colour gives skyline depth.
      const roofGeo = new THREE.ShapeGeometry(shape);
      roofGeo.rotateX(-Math.PI / 2);
      roofGeo.translate(0, height + 0.05, 0);
      const rp = roofGeo.getAttribute('position');
      const rc = new Float32Array(rp.count * 3);
      // Darker grey-brown cap; randomised to feel roof-tar / gravel / metal.
      const roofShade = 0.35 + Math.random() * 0.15;
      for (let i = 0; i < rp.count; i++) {
        rc[i * 3]     = roofShade * 1.0;
        rc[i * 3 + 1] = roofShade * 0.95;
        rc[i * 3 + 2] = roofShade * 0.88;
      }
      roofGeo.setAttribute('color', new THREE.BufferAttribute(rc, 3));
      roofGeos.push(roofGeo);

      count++;
    } catch (e) {
      // Skip invalid geometry
    }
  }

  setLoadingStatus(`Merging ${count} buildings...`, 85);
  if (wallGeos.length === 0) return;

  const wallMerged = THREE.BufferGeometryUtils.mergeBufferGeometries(wallGeos, false);
  for (const g of wallGeos) g.dispose();

  const wallMat = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.78,
    metalness: 0.08,
    flatShading: false,
  });

  buildingMesh = new THREE.Mesh(wallMerged, wallMat);
  buildingMesh.castShadow = true;
  buildingMesh.receiveShadow = true;
  scene.add(buildingMesh);

  if (roofGeos.length > 0) {
    const roofMerged = THREE.BufferGeometryUtils.mergeBufferGeometries(roofGeos, false);
    for (const g of roofGeos) g.dispose();
    const roofMat = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.9,
      metalness: 0.05,
      side: THREE.DoubleSide,
    });
    const roofMesh = new THREE.Mesh(roofMerged, roofMat);
    roofMesh.castShadow = true;
    roofMesh.receiveShadow = true;
    scene.add(roofMesh);
  }

  document.getElementById('stat-buildings').textContent = count.toLocaleString();
}

// ═══════════════════════════════════════════════════════════════════════════════
// ROADS — OSM highway=* rendered as ribbons along the ground
// ═══════════════════════════════════════════════════════════════════════════════

// Road width in meters keyed by OSM highway class.
const ROAD_WIDTH = {
  motorway: 14, trunk: 12, primary: 10, secondary: 8, tertiary: 7,
  residential: 5, unclassified: 5, service: 3.5, living_street: 4,
  pedestrian: 3, footway: 1.8, path: 1.2, cycleway: 2, track: 2.5,
};

async function fetchAndDrawRoads() {
  const bbox = `${CENTER.lat - 0.025},${CENTER.lng - 0.025},${CENTER.lat + 0.025},${CENTER.lng + 0.025}`;
  const query = `[out:json][timeout:45];(way["highway"](${bbox}););out body;>;out skel qt;`;
  try {
    setLoadingStatus('Loading road network...', 78);
    const res = await fetch('https://overpass-api.de/api/interpreter', {
      method: 'POST',
      body: 'data=' + encodeURIComponent(query),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    const data = await res.json();
    const nodes = {};
    for (const el of data.elements) {
      if (el.type === 'node') nodes[el.id] = { lng: el.lon, lat: el.lat };
    }

    const roadGeos = [];
    for (const el of data.elements) {
      if (el.type !== 'way' || !el.tags || !el.tags.highway) continue;
      const cls = el.tags.highway;
      const width = ROAD_WIDTH[cls] || 4;
      const pts = el.nodes.map(nid => nodes[nid]).filter(Boolean).map(c => geoToLocal(c.lng, c.lat));
      if (pts.length < 2) continue;

      // Build a ribbon by extruding perpendicular to each segment.
      const verts = [];
      const indices = [];
      for (let i = 0; i < pts.length; i++) {
        const prev = pts[Math.max(i - 1, 0)];
        const next = pts[Math.min(i + 1, pts.length - 1)];
        let dx = next.x - prev.x;
        let dz = next.z - prev.z;
        const len = Math.sqrt(dx * dx + dz * dz) || 1;
        dx /= len; dz /= len;
        // Perpendicular (rotate 90° in XZ plane)
        const nx = -dz, nz = dx;
        const half = width / 2;
        verts.push(pts[i].x + nx * half, 0.08, pts[i].z + nz * half);
        verts.push(pts[i].x - nx * half, 0.08, pts[i].z - nz * half);
      }
      for (let i = 0; i < pts.length - 1; i++) {
        const a = i * 2, b = i * 2 + 1, c = (i + 1) * 2, d = (i + 1) * 2 + 1;
        indices.push(a, b, c, b, d, c);
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
      geo.setIndex(indices);
      geo.computeVertexNormals();
      roadGeos.push(geo);
    }

    if (roadGeos.length > 0) {
      const merged = THREE.BufferGeometryUtils.mergeBufferGeometries(roadGeos, false);
      for (const g of roadGeos) g.dispose();
      const mat = new THREE.MeshStandardMaterial({
        color: 0x2a2a2e,   // asphalt
        roughness: 0.95,
        metalness: 0.0,
        polygonOffset: true,
        polygonOffsetFactor: -1,
        polygonOffsetUnits: -1,
      });
      const roadMesh = new THREE.Mesh(merged, mat);
      roadMesh.receiveShadow = true;
      scene.add(roadMesh);
    }
  } catch(e) { console.warn('Roads fetch failed:', e); }
}

// ═══════════════════════════════════════════════════════════════════════════════
// VEGETATION — individual trees + park polygons
// ═══════════════════════════════════════════════════════════════════════════════

async function fetchAndDrawVegetation() {
  const bbox = `${CENTER.lat - 0.025},${CENTER.lng - 0.025},${CENTER.lat + 0.025},${CENTER.lng + 0.025}`;
  const query = `[out:json][timeout:45];(
    node["natural"="tree"](${bbox});
    way["leisure"="park"](${bbox});
    way["landuse"="grass"](${bbox});
    way["landuse"="forest"](${bbox});
    way["natural"="wood"](${bbox});
  );out body;>;out skel qt;`;
  try {
    setLoadingStatus('Loading vegetation...', 88);
    const res = await fetch('https://overpass-api.de/api/interpreter', {
      method: 'POST',
      body: 'data=' + encodeURIComponent(query),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    const data = await res.json();
    const nodes = {};
    for (const el of data.elements) {
      if (el.type === 'node') nodes[el.id] = { lng: el.lon, lat: el.lat };
    }

    // ── Park / grass / forest polygons as tinted overlays on the ground ───
    const parkGeos = [];
    const forestGeos = [];
    const treePoints = [];

    for (const el of data.elements) {
      if (el.type === 'way' && el.tags && el.nodes && el.nodes.length >= 3) {
        const pts = el.nodes.map(nid => nodes[nid]).filter(Boolean).map(c => geoToLocal(c.lng, c.lat));
        if (pts.length < 3) continue;
        const shape = new THREE.Shape();
        shape.moveTo(pts[0].x, pts[0].z);
        for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i].x, pts[i].z);
        shape.lineTo(pts[0].x, pts[0].z);
        try {
          const geo = new THREE.ShapeGeometry(shape);
          geo.rotateX(-Math.PI / 2);
          geo.translate(0, 0.25, 0);
          const isWooded = el.tags.landuse === 'forest' || el.tags.natural === 'wood';
          if (isWooded) forestGeos.push(geo); else parkGeos.push(geo);

          // Scatter trees across the polygon (rough AABB rejection-sample).
          const treeDensity = isWooded ? 1 / 150 : 1 / 400;  // 1 tree per 150/400 m²
          const minX = Math.min(...pts.map(p => p.x));
          const maxX = Math.max(...pts.map(p => p.x));
          const minZ = Math.min(...pts.map(p => p.z));
          const maxZ = Math.max(...pts.map(p => p.z));
          const area = (maxX - minX) * (maxZ - minZ);
          const n = Math.min(120, Math.max(1, Math.round(area * treeDensity)));
          for (let i = 0; i < n; i++) {
            const rx = minX + Math.random() * (maxX - minX);
            const rz = minZ + Math.random() * (maxZ - minZ);
            if (pointInPolygon(rx, rz, pts)) treePoints.push({ x: rx, z: rz });
          }
        } catch(e) {}
      } else if (el.type === 'node' && el.tags && el.tags.natural === 'tree') {
        const p = geoToLocal(el.lon, el.lat);
        treePoints.push({ x: p.x, z: p.z });
      }
    }

    if (parkGeos.length > 0) {
      const merged = THREE.BufferGeometryUtils.mergeBufferGeometries(parkGeos, false);
      for (const g of parkGeos) g.dispose();
      const mat = new THREE.MeshStandardMaterial({ color: 0x5a7a3a, roughness: 0.95, transparent: true, opacity: 0.75 });
      const m = new THREE.Mesh(merged, mat);
      m.receiveShadow = true;
      scene.add(m);
    }
    if (forestGeos.length > 0) {
      const merged = THREE.BufferGeometryUtils.mergeBufferGeometries(forestGeos, false);
      for (const g of forestGeos) g.dispose();
      const mat = new THREE.MeshStandardMaterial({ color: 0x3a5a2a, roughness: 0.95, transparent: true, opacity: 0.8 });
      const m = new THREE.Mesh(merged, mat);
      m.receiveShadow = true;
      scene.add(m);
    }

    // Instanced tree meshes — one trunk InstancedMesh + one crown InstancedMesh.
    if (treePoints.length > 0) {
      const trunkGeo = new THREE.CylinderGeometry(0.4, 0.5, 4, 5);
      trunkGeo.translate(0, 2, 0);
      const trunkMat = new THREE.MeshStandardMaterial({ color: 0x4a3420, roughness: 0.95 });
      const crownGeo = new THREE.SphereGeometry(2.5, 8, 6);
      crownGeo.translate(0, 6.2, 0);
      const crownMat = new THREE.MeshStandardMaterial({ color: 0x3d6a2c, roughness: 0.85 });

      const trunks = new THREE.InstancedMesh(trunkGeo, trunkMat, treePoints.length);
      const crowns = new THREE.InstancedMesh(crownGeo, crownMat, treePoints.length);
      trunks.castShadow = crowns.castShadow = true;

      const dummy = new THREE.Object3D();
      for (let i = 0; i < treePoints.length; i++) {
        const p = treePoints[i];
        const scale = 0.8 + Math.random() * 0.8;
        dummy.position.set(p.x, 0, p.z);
        dummy.scale.set(scale, scale, scale);
        dummy.rotation.y = Math.random() * Math.PI * 2;
        dummy.updateMatrix();
        trunks.setMatrixAt(i, dummy.matrix);
        crowns.setMatrixAt(i, dummy.matrix);
      }
      trunks.instanceMatrix.needsUpdate = true;
      crowns.instanceMatrix.needsUpdate = true;
      scene.add(trunks);
      scene.add(crowns);
    }
  } catch(e) { console.warn('Vegetation fetch failed:', e); }
}

function pointInPolygon(x, z, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i].x, zi = poly[i].z;
    const xj = poly[j].x, zj = poly[j].z;
    const intersect = ((zi > z) !== (zj > z)) && (x < (xj - xi) * (z - zi) / (zj - zi + 0.0001) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

// ═══════════════════════════════════════════════════════════════════════════════
// PATH SYSTEM
// ═══════════════════════════════════════════════════════════════════════════════

function addWaypoint(point) {
  pathUndoStack.length = 0;  // clear redo stack on new action
  pathPoints.push(point.clone());
  updatePathVisuals();
  updatePathInfo();
  showToast(`Waypoint ${pathPoints.length} added`);
}

function undoWaypoint() {
  if (pathPoints.length === 0) return;
  pathUndoStack.push(pathPoints.pop());
  updatePathVisuals();
  updatePathInfo();
  showToast('Undo');
}

function redoWaypoint() {
  if (pathUndoStack.length === 0) return;
  pathPoints.push(pathUndoStack.pop());
  updatePathVisuals();
  updatePathInfo();
  showToast('Redo');
}

function resetPath() {
  pathPoints.length = 0;
  pathUndoStack.length = 0;
  updatePathVisuals();
  updatePathInfo();
  showToast('Path reset');
}

function savePath() {
  if (pathPoints.length < 2) {
    showToast('Need at least 2 waypoints to save');
    return;
  }
  const pathData = pathPoints.map((p, i) => ({
    index: i,
    x: p.x,
    y: p.y,
    z: p.z,
    geo: localToGeo(p.x, p.z),
  }));
  const blob = new Blob([JSON.stringify(pathData, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'flight_path.json';
  a.click();
  showToast(`Path saved (${pathPoints.length} waypoints)`);
}

function updatePathVisuals() {
  // Remove old spheres
  for (const s of pathSphereMeshes) scene.remove(s);
  pathSphereMeshes.length = 0;

  // Remove old line
  if (pathLineMesh) { scene.remove(pathLineMesh); pathLineMesh = null; }

  // Draw waypoint spheres
  const sphereGeo = new THREE.SphereGeometry(8, 16, 16);
  for (let i = 0; i < pathPoints.length; i++) {
    const color = i === 0 ? 0x00ff9f : (i === pathPoints.length - 1 ? 0xff2a6d : 0x0088ff);
    const mat = new THREE.MeshBasicMaterial({ color });
    const sphere = new THREE.Mesh(sphereGeo, mat);
    sphere.position.copy(pathPoints[i]);
    sphere.position.y += 10;  // slightly above ground
    scene.add(sphere);
    pathSphereMeshes.push(sphere);
  }

  // Draw path line
  if (pathPoints.length >= 2) {
    const linePoints = pathPoints.map(p => new THREE.Vector3(p.x, p.y + 10, p.z));
    const lineGeo = new THREE.BufferGeometry().setFromPoints(linePoints);
    const lineMat = new THREE.LineBasicMaterial({ color: 0x0088ff, linewidth: 2 });
    pathLineMesh = new THREE.Line(lineGeo, lineMat);
    scene.add(pathLineMesh);
  }

  document.getElementById('stat-waypoints').textContent = pathPoints.length;
}

function updatePathInfo() {
  const el = document.getElementById('path-detail');
  if (pathPoints.length === 0) {
    el.innerHTML = 'No waypoints yet';
    return;
  }
  let totalDist = 0;
  for (let i = 1; i < pathPoints.length; i++) {
    totalDist += pathPoints[i].distanceTo(pathPoints[i - 1]);
  }
  el.innerHTML = `
    <div>Points: <span style="color:#0088ff">${pathPoints.length}</span></div>
    <div>Distance: <span style="color:#0088ff">${(totalDist).toFixed(0)}m</span></div>
    <div style="margin-top:4px;font-size:10px;color:#64748b;">
      ${pathPoints.map((p, i) => {
        const geo = localToGeo(p.x, p.z);
        return `#${i + 1}: ${geo.lat.toFixed(4)}, ${geo.lng.toFixed(4)}`;
      }).join('<br>')}
    </div>
  `;
}

// ═══════════════════════════════════════════════════════════════════════════════
// FLYTHROUGH SYSTEM (scroll-driven camera animation)
// ═══════════════════════════════════════════════════════════════════════════════

function startFlythrough() {
  if (pathPoints.length < 2) {
    showToast('Need at least 2 waypoints for flythrough');
    setMode('edit');
    return;
  }

  controls.enabled = false;
  const scrollContainer = document.getElementById('scroll-container');
  scrollContainer.style.display = 'block';
  scrollContainer.scrollTop = 0;

  scrollContainer.addEventListener('scroll', onFlythroughScroll);
}

function stopFlythrough() {
  controls.enabled = true;
  const scrollContainer = document.getElementById('scroll-container');
  scrollContainer.style.display = 'none';
  scrollContainer.removeEventListener('scroll', onFlythroughScroll);
}

function onFlythroughScroll() {
  const scrollContainer = document.getElementById('scroll-container');
  const scrollTop = scrollContainer.scrollTop;
  const maxScroll = scrollContainer.scrollHeight - scrollContainer.clientHeight;
  const pct = Math.max(0, Math.min(1, scrollTop / maxScroll));

  if (pathPoints.length < 2) return;

  const totalSegments = pathPoints.length - 1;
  const segFloat = pct * totalSegments;
  const segIdx = Math.min(Math.floor(segFloat), totalSegments - 1);
  const segPct = segFloat - segIdx;

  // Interpolate position
  const p1 = pathPoints[segIdx];
  const p2 = pathPoints[segIdx + 1];
  const cx = p1.x + (p2.x - p1.x) * segPct;
  const cy = p1.y + (p2.y - p1.y) * segPct + 60;  // camera height above path
  const cz = p1.z + (p2.z - p1.z) * segPct;

  camera.position.set(cx, cy, cz);

  // Look ahead
  const lookAhead = Math.min(segPct + 0.3, 1);
  const lx = p1.x + (p2.x - p1.x) * lookAhead;
  const ly = p1.y + (p2.y - p1.y) * lookAhead + 20;
  const lz = p1.z + (p2.z - p1.z) * lookAhead;

  // If near end of segment, look at next segment start
  if (segIdx < totalSegments - 1 && segPct > 0.7) {
    const p3 = pathPoints[segIdx + 2];
    const blend = (segPct - 0.7) / 0.3;
    camera.lookAt(
      lx + (p3.x - lx) * blend,
      ly + (p3.y - ly) * blend + 20,
      lz + (p3.z - lz) * blend
    );
  } else {
    camera.lookAt(lx, ly, lz);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// RESCUE DATA (WebSocket connection to dashboard)
// ═══════════════════════════════════════════════════════════════════════════════

function connectWebSocket() {
  const ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onmessage = (event) => {
    try {
      const state = JSON.parse(event.data);
      if (!state.ready) return;
      updateRescueData(state);
    } catch(e) {}
  };

  ws.onclose = () => setTimeout(connectWebSocket, 2000);
  ws.onerror = () => ws.close();
}

// ── One-time scene decoration for mission geography ────────────────────────
// Bases and team sectors are static, so we build them once when the WS state
// first arrives (to avoid racing with the satellite-tile load order).
function createBaseStations() {
  if (baseGroup) return;
  baseGroup = new THREE.Group();

  for (const [name, b] of Object.entries(BASE_STATIONS)) {
    const local = geoToLocal(b.lng, b.lat);

    // Glowing pillar (beacon) — bright emissive so bloom picks it up
    const pillarGeo = new THREE.CylinderGeometry(4, 6, 140, 16);
    const pillarMat = new THREE.MeshStandardMaterial({
      color: b.colour, emissive: b.colour, emissiveIntensity: 1.4, roughness: 0.4, metalness: 0.5,
    });
    const pillar = new THREE.Mesh(pillarGeo, pillarMat);
    pillar.position.set(local.x, 70, local.z);
    pillar.castShadow = true;
    baseGroup.add(pillar);

    // Base pad — flat disc at ground level
    const padGeo = new THREE.CylinderGeometry(28, 30, 2, 32);
    const padMat = new THREE.MeshStandardMaterial({
      color: 0x181820, emissive: b.colour, emissiveIntensity: 0.25, roughness: 0.6, metalness: 0.3,
    });
    const pad = new THREE.Mesh(padGeo, padMat);
    pad.position.set(local.x, 1, local.z);
    pad.receiveShadow = true;
    baseGroup.add(pad);

    // Ring marker around pad
    const ringGeo = new THREE.RingGeometry(30, 34, 48);
    const ringMat = new THREE.MeshBasicMaterial({ color: b.colour, transparent: true, opacity: 0.8, side: THREE.DoubleSide });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(local.x, 1.5, local.z);
    baseGroup.add(ring);
  }

  scene.add(baseGroup);
}

function createTeamSectors() {
  if (sectorGroup) return;
  sectorGroup = new THREE.Group();

  const centre = geoToLocal(BASE_CENTER_GEO.lng, BASE_CENTER_GEO.lat);
  const R = SECTOR_RADIUS_M;

  for (const s of TEAM_SECTORS) {
    // Compass bearing: 0°=N, 90°=E. In scene: +X=east, -Z=north.
    // Angle to (dx, dz): bearing 0 → (0, -R); bearing 90 → (R, 0).
    const startRad = THREE.MathUtils.degToRad(s.start);
    const endRad   = THREE.MathUtils.degToRad(s.end);

    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    const steps = 32;
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const ang = startRad + (endRad - startRad) * t;
      const dx =  Math.sin(ang) * R;
      const dz = -Math.cos(ang) * R;
      if (i === 0) shape.lineTo(dx, dz); else shape.lineTo(dx, dz);
    }
    shape.lineTo(0, 0);

    const geo = new THREE.ShapeGeometry(shape);
    geo.rotateX(-Math.PI / 2);
    geo.translate(centre.x, 0.5, centre.z);
    const mat = new THREE.MeshBasicMaterial({
      color: s.colour, transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false,
    });
    const mesh = new THREE.Mesh(geo, mat);
    sectorGroup.add(mesh);

    // Outline for the slice edge
    const pts = [];
    pts.push(new THREE.Vector3(centre.x, 0.8, centre.z));
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const ang = startRad + (endRad - startRad) * t;
      const dx =  Math.sin(ang) * R;
      const dz = -Math.cos(ang) * R;
      pts.push(new THREE.Vector3(centre.x + dx, 0.8, centre.z + dz));
    }
    pts.push(new THREE.Vector3(centre.x, 0.8, centre.z));
    const lineGeo = new THREE.BufferGeometry().setFromPoints(pts);
    const lineMat = new THREE.LineBasicMaterial({ color: s.colour, transparent: true, opacity: 0.35 });
    sectorGroup.add(new THREE.Line(lineGeo, lineMat));
  }

  scene.add(sectorGroup);
}

// ── Drone quadcopter mesh (persistent; only transform updates per tick) ────
function buildDroneMesh(colour) {
  const g = new THREE.Group();
  // Body
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(8, 3, 8),
    new THREE.MeshStandardMaterial({ color: 0x222831, roughness: 0.4, metalness: 0.7 })
  );
  g.add(body);
  // Arms (X-shape)
  const armMat = new THREE.MeshStandardMaterial({ color: 0x111418, roughness: 0.3, metalness: 0.9 });
  for (let i = 0; i < 4; i++) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(14, 1.2, 1.2), armMat);
    arm.rotation.y = i * Math.PI / 2 + Math.PI / 4;
    g.add(arm);
    // Rotor pad at the tip
    const tipX =  Math.cos(i * Math.PI / 2 + Math.PI / 4) * 7;
    const tipZ = -Math.sin(i * Math.PI / 2 + Math.PI / 4) * 7;
    const rotor = new THREE.Mesh(
      new THREE.CylinderGeometry(3.2, 3.2, 0.3, 12),
      new THREE.MeshStandardMaterial({ color: 0x2a2a2a, roughness: 0.5 })
    );
    rotor.position.set(tipX, 1.2, tipZ);
    g.add(rotor);
  }
  // Status LED underbelly — uses role colour, emissive so bloom picks it up
  const led = new THREE.Mesh(
    new THREE.SphereGeometry(1.2, 8, 8),
    new THREE.MeshBasicMaterial({ color: colour })
  );
  led.position.y = -1.6;
  g.add(led);

  // Scan-radius ring (100 m in world units)
  const ringGeo = new THREE.RingGeometry(VISION_RADIUS_M - 2, VISION_RADIUS_M, 64);
  const ringMat = new THREE.MeshBasicMaterial({
    color: colour, transparent: true, opacity: 0.45, side: THREE.DoubleSide,
  });
  const scanRing = new THREE.Mesh(ringGeo, ringMat);
  scanRing.rotation.x = -Math.PI / 2;
  scanRing.userData.isScanRing = true;
  g.add(scanRing);

  // Faint filled scan disc
  const discGeo = new THREE.CircleGeometry(VISION_RADIUS_M, 64);
  const discMat = new THREE.MeshBasicMaterial({
    color: colour, transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false,
  });
  const scanDisc = new THREE.Mesh(discGeo, discMat);
  scanDisc.rotation.x = -Math.PI / 2;
  g.add(scanDisc);

  // Target beam (vertical line to ground) — updated per-frame
  const beamMat = new THREE.LineBasicMaterial({ color: colour, transparent: true, opacity: 0.4 });
  const beamGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, -60, 0),
  ]);
  const beam = new THREE.Line(beamGeo, beamMat);
  beam.userData.isBeam = true;
  g.add(beam);

  return g;
}

function droneColourFor(d) {
  if (d.slot === 'CMD') return DRONE_COLOURS.CMD;
  if (d.ring_role === 'OUTER') return DRONE_COLOURS.OUTER;
  if (d.ring_role === 'INNER') return DRONE_COLOURS.INNER;
  return DRONE_COLOURS.MIDDLE;
}

// Persistent drone registry: id → { group, pathLine, colour }
const droneRegistry = {};

function updateRescueData(state) {
  // Update stats
  document.getElementById('stat-survivors').textContent =
    `${state.rescued || 0}/${state.total || 0}`;
  document.getElementById('stat-drones').textContent =
    (state.drones || []).length;

  // Lazy-build the static mission geography on first real state tick
  createBaseStations();
  createTeamSectors();

  // ── Survivors ─────────────────────────────────────────────────────────
  // Cheap approach: rebuild on each update. Typical count is small enough.
  for (const m of survivorMeshes) scene.remove(m);
  survivorMeshes.length = 0;

  const survGeo = new THREE.SphereGeometry(4, 10, 10);
  for (const s of (state.survivors || [])) {
    if (s.rescued) continue;
    const local = geoToLocal(s.x, s.y);
    const colour = s.critical ? 0xff2a6d : 0xff9500;
    const mat = new THREE.MeshBasicMaterial({ color: colour });
    const mesh = new THREE.Mesh(survGeo, mat);
    mesh.position.set(local.x, 4, local.z);
    scene.add(mesh);
    survivorMeshes.push(mesh);

    // Detected survivors get a red 50 m ring (matches 2D detection ring).
    if (s.detected) {
      const ringGeo = new THREE.RingGeometry(48, 52, 32);
      const ringMat = new THREE.MeshBasicMaterial({
        color: 0xff2a6d, transparent: true, opacity: 0.55, side: THREE.DoubleSide,
      });
      const ring = new THREE.Mesh(ringGeo, ringMat);
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(local.x, 2, local.z);
      ring.userData.pulse = true;
      scene.add(ring);
      survivorMeshes.push(ring);
    }
  }

  // ── Drones (persistent per id) ────────────────────────────────────────
  const seen = new Set();
  for (const d of (state.drones || [])) {
    seen.add(d.id);
    const colour = droneColourFor(d);
    let entry = droneRegistry[d.id];
    if (!entry) {
      const group = buildDroneMesh(colour);
      scene.add(group);
      entry = { group, pathLine: null, colour };
      droneRegistry[d.id] = entry;
    }
    const local = geoToLocal(d.x, d.y);
    // Altitude: outer drones fly higher, inner scan low
    const altitude = d.ring_role === 'OUTER' ? 85
                   : d.ring_role === 'INNER' ? 45 : 65;
    entry.group.position.set(local.x, altitude, local.z);

    // Spin rotors + face target for a little life
    if (d.target) {
      const tgtLocal = geoToLocal(d.target.x, d.target.y);
      const dx = tgtLocal.x - local.x;
      const dz = tgtLocal.z - local.z;
      entry.group.rotation.y = Math.atan2(dx, -dz);
    }

    // Update path polyline (refresh buffer in place if already present)
    const pathPts = [];
    pathPts.push(new THREE.Vector3(local.x, altitude - 2, local.z));
    if (d.path && d.path.length) {
      for (const p of d.path) {
        const pl = geoToLocal(p.x, p.y);
        pathPts.push(new THREE.Vector3(pl.x, altitude - 2, pl.z));
      }
    } else if (d.target) {
      const tgtLocal = geoToLocal(d.target.x, d.target.y);
      pathPts.push(new THREE.Vector3(tgtLocal.x, altitude - 2, tgtLocal.z));
    }
    if (entry.pathLine) { scene.remove(entry.pathLine); entry.pathLine.geometry.dispose(); }
    if (pathPts.length >= 2) {
      const pg = new THREE.BufferGeometry().setFromPoints(pathPts);
      const pm = new THREE.LineBasicMaterial({ color: colour, transparent: true, opacity: 0.6 });
      entry.pathLine = new THREE.Line(pg, pm);
      scene.add(entry.pathLine);
    } else {
      entry.pathLine = null;
    }
  }

  // Remove drones that disappeared from the simulation
  for (const id of Object.keys(droneRegistry)) {
    if (!seen.has(id)) {
      scene.remove(droneRegistry[id].group);
      if (droneRegistry[id].pathLine) scene.remove(droneRegistry[id].pathLine);
      delete droneRegistry[id];
    }
  }

  // ── Flood / disaster cells ────────────────────────────────────────────
  // The 2D dashboard keeps these static, but they rarely change — rebuild
  // only when the count changes to avoid per-tick churn.
  const cells = state.disaster_cells || [];
  if (cells.length !== floodMeshes.length) {
    for (const m of floodMeshes) scene.remove(m);
    floodMeshes.length = 0;
    for (const c of cells) {
      // disaster_cells are [lng, lat] or [x, y] — use raw geo
      const lng = Array.isArray(c) ? c[0] : c.x;
      const lat = Array.isArray(c) ? c[1] : c.y;
      if (typeof lng !== 'number' || typeof lat !== 'number') continue;
      const local = geoToLocal(lng, lat);
      const pool = new THREE.Mesh(
        new THREE.CylinderGeometry(35, 35, 2.5, 24),
        new THREE.MeshStandardMaterial({
          color: 0x2a4d7a, emissive: 0x3a7ab8, emissiveIntensity: 0.3,
          roughness: 0.15, metalness: 0.6, transparent: true, opacity: 0.72,
        })
      );
      pool.position.set(local.x, 1.3, local.z);
      pool.receiveShadow = true;
      scene.add(pool);
      floodMeshes.push(pool);
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// MODE MANAGEMENT
// ═══════════════════════════════════════════════════════════════════════════════

function setMode(newMode) {
  mode = newMode;
  document.getElementById('btn-edit').classList.toggle('active', mode === 'edit');
  document.getElementById('btn-fly').classList.toggle('active', mode === 'fly');
  document.getElementById('btn-orbit').classList.toggle('active', mode === 'orbit');

  document.getElementById('crosshair').style.display = mode === 'edit' ? 'block' : 'none';
  document.getElementById('help-panel').style.display = mode === 'edit' ? 'block' : 'none';
  document.getElementById('path-info').classList.toggle('visible', mode === 'edit' || mode === 'fly');

  if (mode === 'fly') {
    startFlythrough();
  } else {
    stopFlythrough();
  }

  if (mode === 'orbit') {
    controls.enabled = true;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.5;
  } else {
    controls.autoRotate = false;
  }

  if (mode === 'edit') {
    controls.enabled = true;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// EVENT HANDLERS
// ═══════════════════════════════════════════════════════════════════════════════

function onMouseClick(event) {
  if (mode !== 'edit') return;
  // Ignore clicks on UI elements
  if (event.target.closest('#hud') || event.target.closest('#help-panel') || event.target.closest('#path-info')) return;

  mouse.x = (event.clientX / window.innerWidth) * 2 - 1;
  mouse.y = -(event.clientY / window.innerHeight) * 2 + 1;

  raycaster.setFromCamera(mouse, camera);
  const intersects = raycaster.intersectObject(groundMesh);

  if (intersects.length > 0) {
    addWaypoint(intersects[0].point);
  }
}

function onKeyDown(event) {
  if (event.target.tagName === 'INPUT') return;
  switch (event.key.toLowerCase()) {
    case 's': savePath(); break;
    case 'z': undoWaypoint(); break;
    case 'x': redoWaypoint(); break;
    case 'r': resetPath(); break;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// UTILITIES
// ═══════════════════════════════════════════════════════════════════════════════

function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 2000);
}

function setLoadingStatus(msg, pct) {
  document.getElementById('loading-status').textContent = msg;
  document.getElementById('loading-bar').style.width = pct + '%';
}

// ═══════════════════════════════════════════════════════════════════════════════
// ANIMATION LOOP
// ═══════════════════════════════════════════════════════════════════════════════

let clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime();

  controls.update();

  // Pulse detection rings on survivors
  for (let i = 0; i < survivorMeshes.length; i++) {
    const m = survivorMeshes[i];
    if (m.userData && m.userData.pulse) {
      m.scale.setScalar(1 + 0.18 * Math.sin(t * 3 + i));
      m.material.opacity = 0.35 + 0.25 * Math.sin(t * 3 + i);
    }
  }

  // Per-drone: bob slightly, spin rotors, pulse scan ring
  let droneIdx = 0;
  for (const id in droneRegistry) {
    const entry = droneRegistry[id];
    const g = entry.group;
    g.position.y += Math.sin(t * 3 + droneIdx) * 0.08;  // tiny hover jitter
    // Spin rotors (children 1..4 = arms+rotors group; rotors are the cylinder pads)
    for (const child of g.children) {
      if (child.geometry && child.geometry.type === 'CylinderGeometry' && child.position.y > 0) {
        child.rotation.y += 0.6;
      }
      if (child.userData && child.userData.isScanRing) {
        const s = 1 + 0.06 * Math.sin(t * 4 + droneIdx);
        child.scale.set(s, s, 1);
      }
    }
    droneIdx++;
  }

  if (composer) composer.render();
  else renderer.render(scene, camera);
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN
// ═══════════════════════════════════════════════════════════════════════════════

async function main() {
  setLoadingStatus('Initializing 3D engine...', 5);
  initScene();
  setupPostProcessing();

  // Satellite ground tiles load in parallel with the OSM queries — the tiles
  // appear first and the vector layers snap into place on top as they arrive.
  const satPromise = loadSatelliteTiles().catch(e => console.warn('Sat tiles failed:', e));

  // Fetch and render buildings
  try {
    const elements = await fetchBuildings();
    const buildings = parseBuildings(elements);
    createBuildingMeshes(buildings);
  } catch (e) {
    console.error('Building fetch failed:', e);
    setLoadingStatus('Building data unavailable', 70);
  }

  // Ancillary layers load in background (non-blocking)
  fetchAndDrawRoads().catch(() => {});
  fetchAndDrawVegetation().catch(() => {});
  await satPromise;

  setLoadingStatus('Connecting to mission data...', 95);

  // Connect to rescue data WebSocket
  connectWebSocket();

  // Event listeners
  window.addEventListener('click', onMouseClick);
  window.addEventListener('keydown', onKeyDown);

  // Start render loop
  setLoadingStatus('Ready', 100);
  setTimeout(() => {
    document.getElementById('loading-screen').style.opacity = '0';
    document.getElementById('loading-screen').style.transition = 'opacity 0.5s';
    setTimeout(() => document.getElementById('loading-screen').style.display = 'none', 500);
  }, 500);

  setMode('edit');
  animate();
}

main();
</script>
</body>
</html>"""

@dashboard_app.get("/3d", response_class=HTMLResponse)
async def city_3d():
    return _HTML_3D

