"""Generate a single-file HTML viewer for the fused scene-reconstruction meshes.

Embeds the orbit-scan and full arm-scan PLYs as base64 (like the earlier
Claude artifact) so the page is portable: open it straight from disk, no
server needed. three.js comes from a pinned CDN (import map).

Usage:
    uv run python tools/mapper_probe/make_viewer.py \
        --out data/runs/mapper_probe/viewer.html
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = REPO_ROOT / "data" / "runs" / "mapper_probe"

ARM_FULL_PLY = RUN_DIR / "arm_scan_full" / "reconstructed_scene.ply"
ORBIT_PLY = RUN_DIR / "reconstructed_scene.ply"
MESHES = (
    ("arm-full", "Arm scan 5-by-3", ARM_FULL_PLY),
    ("orbit", "Orbit scan 16-frame", ORBIT_PLY),
)

THREE_VERSION = "0.160.0"

HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ANTS scene reconstruction probe</title>
<style>
  html, body { margin: 0; height: 100%; overflow: hidden; background: #101418;
    font-family: system-ui, sans-serif; color: #dfe6ee; }
  #app { position: fixed; inset: 0; }
  canvas { display: block; }
  #panel { position: fixed; top: 12px; left: 12px; max-width: 320px;
    background: rgba(16, 20, 24, 0.82); border: 1px solid #2c3642;
    border-radius: 10px; padding: 12px 14px; }
  #panel h1 { font-size: 15px; margin: 0 0 4px; }
  #panel p { font-size: 12px; margin: 4px 0; color: #aebdcc; }
  #panel .row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  #panel button { background: #223041; color: #dfe6ee; border: 1px solid #3a4a5e;
    border-radius: 6px; padding: 6px 10px; font-size: 12px; cursor: pointer; }
  #panel button[aria-pressed="true"] { background: #33507a; border-color: #5b83bd; }
  #panel label { font-size: 12px; display: flex; gap: 6px; align-items: center; }
  #err { position: fixed; left: 12px; bottom: 12px; right: 12px; display: none;
    background: #5a1f1f; border: 1px solid #a33; border-radius: 8px;
    padding: 8px 12px; font-size: 12px; white-space: pre-wrap; }
</style>
<script type="importmap">
{
  "imports": {
    "three": "https://cdn.jsdelivr.net/npm/three@__THREE_VERSION__/build/three.module.js",
    "three/addons/": "https://cdn.jsdelivr.net/npm/three@__THREE_VERSION__/examples/jsm/"
  }
}
</script>
</head>
<body>
<div id="app"></div>
<div id="panel">
  <h1>ANTS scene reconstruction</h1>
  <p id="stats">loading&hellip;</p>
  <p>Drag to orbit &middot; scroll to zoom &middot; right-drag to pan.</p>
  <p>Table-top coverage only; the scan never saw the underside.</p>
  <div class="row" id="meshbtns"></div>
  <div class="row">
    <label><input type="checkbox" id="spin" checked> slow spin</label>
  </div>
</div>
<div id="err" role="alert"></div>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { PLYLoader } from 'three/addons/loaders/PLYLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const errBox = document.getElementById('err');
function showError(msg) {
  errBox.style.display = 'block';
  errBox.textContent += msg + '\\n';
}
window.addEventListener('error', (e) => showError('Error: ' + e.message));
window.addEventListener('unhandledrejection', (e) => showError('Rejection: ' + e.reason));

// __MESH_DATA__ is replaced by the generator with:
//   const MESHES = [{id, label, base64}, ...];

const app = document.getElementById('app');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
app.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101418);
scene.fog = new THREE.Fog(0x101418, 4, 12);

const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.01, 100);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxDistance = 8;

const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

const sun = new THREE.DirectionalLight(0xfff2e0, 2.2);
sun.position.set(2.5, 4, 1.5);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
scene.add(sun);
scene.add(new THREE.HemisphereLight(0xbcd0e8, 0x2a241d, 0.7));

const grid = new THREE.GridHelper(4, 40, 0x3a4a5e, 0x232c38);
grid.position.y = 0;
scene.add(grid);

const loader = new PLYLoader();
const statsEl = document.getElementById('stats');
const btnsEl = document.getElementById('meshbtns');
const spinEl = document.getElementById('spin');
if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) spinEl.checked = false;

let current = null;
function b64ToBuffer(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}
function showMesh(entry) {
  const geometry = loader.parse(b64ToBuffer(entry.base64));
  if (!geometry.hasAttribute('normal')) geometry.computeVertexNormals();
  geometry.rotateX(-Math.PI / 2); // PLY is z-up (world), three.js is y-up
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  const box = geometry.boundingBox;
  const center = box.getCenter(new THREE.Vector3());
  geometry.translate(-center.x, -box.min.y, -center.z);
  const size = box.getSize(new THREE.Vector3()).length();
  const material = new THREE.MeshStandardMaterial({
    vertexColors: geometry.hasAttribute('color'),
    color: geometry.hasAttribute('color') ? 0xffffff : 0xc8b9a0,
    roughness: 0.85,
    metalness: 0.0,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  if (current) {
    scene.remove(current.mesh);
    current.mesh.geometry.dispose();
    current.mesh.material.dispose();
  }
  current = { mesh, id: entry.id };
  scene.add(mesh);
  const dist = Math.max(size * 1.4, 1.2);
  camera.position.set(dist * 0.8, dist * 0.6, dist * 0.8);
  controls.target.set(0, size * 0.25, 0);
  controls.update();
  const nv = geometry.hasAttribute('position') ? geometry.getAttribute('position').count : 0;
  const nf = geometry.index ? geometry.index.count / 3 : 0;
  statsEl.textContent = entry.label + ' — ' + nv.toLocaleString() + ' verts, ' +
    Math.round(nf).toLocaleString() + ' faces';
  for (const b of btnsEl.querySelectorAll('button')) {
    b.setAttribute('aria-pressed', b.dataset.id === entry.id ? 'true' : 'false');
  }
}
for (const entry of MESHES) {
  const b = document.createElement('button');
  b.textContent = entry.label.split(' (')[0];
  b.dataset.id = entry.id;
  b.setAttribute('aria-pressed', 'false');
  b.addEventListener('click', () => showMesh(entry));
  btnsEl.appendChild(b);
}
showMesh(MESHES[0]);

window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

let last = performance.now();
function tick(now) {
  requestAnimationFrame(tick);
  const dt = Math.min((now - last) / 1000, 0.1);
  last = now;
  if (spinEl.checked && current) current.mesh.rotation.y += dt * 0.15;
  controls.update();
  renderer.render(scene, camera);
}
requestAnimationFrame(tick);
</script>
</body>
</html>
"""


def build_html(mesh_b64: dict[str, tuple[str, str]]) -> str:
    entries = ",\n".join(
        f'  {{id: "{mid}", label: "{label}", base64: "{mesh_b64[mid][1]}"}}'
        for mid, label, _path in MESHES
    )
    page = HTML_HEAD.replace("__THREE_VERSION__", THREE_VERSION)
    page = page.replace(
        "// __MESH_DATA__ is replaced by the generator with:\n"
        "//   const MESHES = [{id, label, base64}, ...];",
        f"const MESHES = [\n{entries}\n];",
    )
    return page


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=RUN_DIR / "viewer.html")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mesh_b64: dict[str, tuple[str, str]] = {}
    for mid, label, path in MESHES:
        raw = path.read_bytes()
        print(f"[viewer] {mid}: {path} ({len(raw) / 1024:.0f} KiB)")
        mesh_b64[mid] = (label, base64.b64encode(raw).decode("ascii"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_html(mesh_b64), encoding="utf-8")
    print(f"[viewer] wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
