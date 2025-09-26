# ABOUT

## Live Depth Point Cloud + Rain Collisions

This project is a real-time, browser-based visualizer that turns a live **depth + RGB** stream into a 3D **point cloud** with **rain particles** that collide against the reconstructed surface. A lightweight **color/shape FX pipeline** (hue, brightness, contrast, B&W threshold, and tint modes) and **procedural point sprites** (square, circle, cross) let you stylize the cloud without any post-processing frameworks. You can orbit the camera, pause, export screenshots, and even generate **glTF/GLB** exports (as a downsampled surface mesh or the live points).

Everything runs client-side in **Three.js**; frames are fed over **WebSocket** from a companion process (you provide) at `ws://localhost:8765`.

---

## Highlights

* ⚡ **Live point cloud** from depth+RGB frames (unprojected by intrinsics)
* 🌧️ **Rain simulation** with collisions against the current cloud (several hit behaviors)
* 🎚 **Color FX**: filter modes (mono, invert, invert+mono, tint red, red→yellow), **hue**, **brightness**, **contrast**, optional **B&W threshold**
* 🔵 **Point shapes**: square (fast), **circle**, **cross (+)** with soft edges and thickness/feather controls
* 🖱 **Orbit controls**, pause, fullscreen, PNG capture
* 📦 **Export** GLB/GLTF:

  * Surface mesh reconstruction from the grid (configurable stride & edge filter)
  * Fallback export of the live **Points** cloud
* 🧰 **lil-gui** control panel organized into **Color**, **Points**, **Rain**
* 🚀 No build step required – uses CDN import maps (run behind a local static server)

---

## How it works

### 1) Frame ingestion (WebSocket)

A tiny binary protocol feeds frames to the browser:

```
[uint32 headerLen][JSON header][padding to 4B][Float32 depth[N]][Uint8 rgb[3N]]
```

* **header JSON**: `{ w, h, fx, fy, cx, cy }`
* **N** = `w*h`
* **depth**: row-major, meters (Float32)
* **rgb**: interleaved R,G,B in 0–255

The client reads each message, parses the header, and maps the depth grid back to camera space using the intrinsics. It keeps a **double buffer** (`lastPos`, `nextPos`) and **tweens** between them for temporal smoothing.

### 2) Unprojection → `THREE.BufferGeometry`

For each pixel `(u, v)` with depth `Z`:

```
X = (u - cx)/fx * Z
Y = (v - cy)/fy * Z
Z = Z
```

Coordinates are re-oriented so the camera looks down `-Z` and `Y` is up. Positions and colors are stored in typed arrays and exposed as `BufferAttributes` on a shared `BufferGeometry`. A single `THREE.PointsMaterial` renders the cloud.

### 3) Color pipeline (CPU-side)

Every new frame writes raw RGB (0..1) into `baseCol`. A fast CPU pass fills `curCol`:

1. **Filter mode**: none / monochrome / invert / invert+mono / tint red / red→yellow
2. **Hue rotation** (matrix-based, degrees)
3. **Brightness** (scalar gain)
4. **Contrast** (`c' = (c−0.5)·contrast + 0.5`)
5. **B&W threshold** (optional, on luminance)
6. **Clamp** to 0..1

The result is uploaded to the `color` attribute.

### 4) Point shapes (procedural sprites)

* **square**: plain `PointsMaterial` (no texture), fastest
* **circle** / **cross**: a tiny **CanvasTexture** with alpha controls:

  * `shapeFeather` softens edges
  * `crossThickness` widens the bars
    Textures are generated on the fly and bound to `PointsMaterial.map` with `alphaTest=0.5` (no heavy blending).

### 5) Rain simulation & collisions

A pool of particles (positions, velocities, colors) is stepped each frame:

* Gravity with a **speed multiplier (`rainSpeed`)**
* Several **hit behaviors** on collision with the cloud:

  * **STICK** (flash + dwell)
  * **FLY_UP** (impulse upward)
  * **RADIAL** (push away from cloud center)
  * **RANDOM** (scatter)
* **Collision grid**: the cloud is voxelized into a sparse hash grid (`CELL` size, neighbor checks) from the **latest** positions. A small search radius tests hits efficiently.

### 6) Mesh reconstruction (for export)

When exporting, an optional **surface mesh** is built by downsampling the depth grid (configurable `exportStride`) and triangulating 2×2 quads where **edge lengths** are below `maxEdge`, producing a fairly robust, hole-aware surface. If no valid triangles are produced, the exporter falls back to a `THREE.Points` node.

---

## Controls

### Keyboard

* `P` – Pause / resume (renders one frame when paused)
* `F` – Fullscreen toggle
* `S` – Save PNG of the canvas
* `1..4` – Switch rain hit behavior (stick / fly-up / radial / random)
* `G` – Export **GLB** (binary)
* `Shift+G` – Export **GLTF** (JSON)
* `T` – Cycle filter mode

### GUI (lil-gui)

**Color**

* **Mode**: None, Monochrome, Invert, Invert+Mono, Tint Red, Red→Yellow
* **Hue Rotation** (°)
* **Brightness** (0.25–2.0)
* **Contrast** (0.2–3.0)
* **B&W Threshold** (toggle) + **Threshold** (0–1)
* **Clamp 0..1** (toggle)
* **Tint Amount** (only in *Tint Red*)

**Points**

* **Size** (sprite size in world space)
* **Shape**: square / circle / cross
* **Edge Softness** (circle & cross)
* **Cross Thickness** (cross only)

**Rain**

* **Speed** (scales gravity, impulses, spawn velocities)

---

## Running locally

Because ES modules are imported via `<script type="importmap">`, you must serve the file over **HTTP** (not `file://`).

1. Start a simple static server in the project folder:

```bash
# pick one you have handy
python -m http.server 8000
# or
npx http-server -p 8000
```

2. Ensure your depth producer runs a WebSocket server at:

```
ws://localhost:8765
```

and sends frames in the format described above.

3. Open the app:

```
http://localhost:8000/     # navigate to your HTML file
```

> Tip: if you host the HTML under a different origin, adjust the `WebSocket` URL accordingly.

---

## Frame format (reference)

* **Prefix**: `uint32` little-endian `headerLen`
* **Header** (UTF-8 JSON, `headerLen` bytes):

  ```json
  { "w": <int>, "h": <int>, "fx": <float>, "fy": <float>, "cx": <float>, "cy": <float> }
  ```
* **Padding**: align to 4-byte boundary after the header
* **Depth**: `Float32Array` of length `w*h` (meters)
* **RGB**: `Uint8Array` length `w*h*3`, interleaved

The client treats non-finite depths as invalid (skipped in mesh building; points can still exist if values are finite).

---

## Exporting

* **GLB**: compact binary via `GLTFExporter` (`options: binary, embedImages, onlyVisible`)
* **GLTF (JSON)**: human-readable; textures embedded
* **Surface mesh**: `exportStride` (default 2) and `maxEdge` (default `0.08m`) control density and triangle acceptance
* **Fallback**: if the mesh would be empty, exports the live `Points` instead

Exports include **per-vertex colors**.

---

## Performance tips

* Prefer **square** points for maximum throughput; use **circle/cross** when you need the look
* Reduce **point size** or the upstream **depth resolution** if GPU is saturated
* Lower **RAIN_COUNT** or increase **CELL** size if CPU spikes
* Keep **exportStride** higher and **maxEdge** conservative to avoid overly dense meshes
* Pausing (`P`) lets you examine a single frame and still use the GUI

---

## Project layout & dependencies

* Single-file HTML app, modules via **CDN**:

  * `three` `^0.180`
  * `three/addons` (OrbitControls, GLTFExporter)
  * `lil-gui` `^0.18`
* No bundler required; just run behind a static server
* The WebSocket producer is **out of scope** here (bring your own). Any device that can output depth + RGB + intrinsics per frame will work (e.g., stereo, ToF, SLAM).

---

## Troubleshooting

* **Blank screen / console error**: run over HTTP(S), not `file://`
* **Not connecting**: check the WebSocket server URL, CORS/firewall, and that it emits the expected binary structure
* **Flicker in colors**: ensure RGB and depth originate from the same timestamp/frame; mismatched streams will smear during tweening
* **Jagged edges in point sprites**: increase `shapeFeather` or try square points
* **Slow exports**: increase `exportStride` and/or `maxEdge` filters fewer triangles

---

## Keyboard cheat-sheet

`P` pause • `F` fullscreen • `S` PNG • `1..4` rain modes • `G` GLB • `Shift+G` GLTF • `T` filter mode

---

## License

Choose a license that fits your project (MIT/Apache-2.0/etc.). Add the full text as `LICENSE`.

---

## Credits

Built with ❤️ using **Three.js** and **lil-gui**.
Thanks to the open-source community for the excellent tooling.

---

## Roadmap (nice-to-haves)

* Attribute-driven **per-point glyphs** (mixed shapes in one draw)
* **Normals from depth** for lit point sprites
* GPU compute for rain (WebGPU/TFB)
* Color grading LUTs and filmic tone mapping presets

