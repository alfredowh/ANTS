/* Live mirror: 3D view of the rollout in progress, in the live panel. Everything drawn comes from the
   simulator's own state (tools/ants_live_hook/ants_live_mirror.py), so it is a mirror of the
   simulator, not a reconstruction. three.js loads on first use; polling only. */
(function () {
  const POLL_MS = 125, PREF = "ants-studio-mirror";
  let enabled = false; // off by default: the column is for the two cameras
  try { enabled = localStorage.getItem(PREF) === "1"; } catch (e) {}
  let loaded = null, three = null, scene, camera, renderer, controls, contacts;
  let modelId = null, objects = [], busy = false, status = {active: false}, shown = false, dirty = false, cam0 = null;
  const layers = {robot: [], scene: []};

  const panel = document.getElementById("live-panel");
  const head = document.getElementById("live-head");
  const foot = document.getElementById("live-foot");
  const box = document.createElement("div");
  box.id = "live-mirror";
  box.hidden = true;
  box.innerHTML = `<div class="mirror-badge" title="Robot, objects and contacts are drawn from the simulator's own model and state at the step shown. Nothing here is estimated, and it is not what the robot's perception saw.">LIVE MIRROR · SIMULATOR TRUTH</div>
    <div class="mirror-tools">
      <label><input type="checkbox" id="mirror-robot" checked>robot</label>
      <label><input type="checkbox" id="mirror-scene" checked>scene</label>
      <label><input type="checkbox" id="mirror-contacts" checked>contacts</label>
      <button type="button" id="mirror-view" title="Back to the simulator's agentview camera, the same view as the left image">reset view</button>
    </div>
    <div class="mirror-note" id="mirror-note"></div>`;
  panel.insertBefore(box, foot);
  const toggle = document.createElement("button");
  toggle.id = "mirror-toggle";
  toggle.type = "button";
  toggle.textContent = "3D";
  toggle.title = "Show or hide the Live mirror";
  head.appendChild(toggle);
  const note = document.getElementById("mirror-note");

  function loadScript(src) {
    return new Promise((ok, bad) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = ok;
      s.onerror = () => bad(new Error(src));
      document.head.appendChild(s);
    });
  }
  function loadThree() {
    if (!loaded) {
      loaded = loadScript("https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js")
        .then(() => loadScript("https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"))
        .then(() => { three = window.THREE; setup(); });
    }
    return loaded;
  }

  function setup() {
    scene = new three.Scene();
    scene.background = new three.Color(0x14171c);
    scene.add(new three.HemisphereLight(0xffffff, 0x445566, 0.9));
    const sun = new three.DirectionalLight(0xffffff, 0.6);
    sun.position.set(1, -1, 3);
    scene.add(sun);
    camera = new three.PerspectiveCamera(45, 2, 0.02, 30);
    camera.up.set(0, 0, 1); // MuJoCo world: z up
    renderer = new three.WebGLRenderer({antialias: true, preserveDrawingBuffer: true});
    box.insertBefore(renderer.domElement, box.firstChild);
    controls = new three.OrbitControls(camera, renderer.domElement);
    controls.addEventListener("change", () => { dirty = true; });
    contacts = new three.Points(new three.BufferGeometry(), new three.PointsMaterial({color: 0xff3b30, size: 0.018, depthTest: false}));
    contacts.frustumCulled = false;
    contacts.renderOrder = 2;
    scene.add(contacts);
    resize();
    new ResizeObserver(resize).observe(box);
    (function draw() {
      requestAnimationFrame(draw);
      if (dirty && !box.hidden) { renderer.render(scene, camera); dirty = false; }
    })();
  }
  function resize() {
    if (!renderer || !box.clientWidth) return;
    renderer.setSize(box.clientWidth, box.clientHeight, false);
    camera.aspect = box.clientWidth / box.clientHeight;
    camera.updateProjectionMatrix();
    dirty = true;
  }

  function primitive(g) {
    const s = g.size;
    if (g.type === 0) return new three.PlaneGeometry((s[0] || 2) * 2, (s[1] || 2) * 2);
    if (g.type === 2) return new three.SphereGeometry(s[0], 16, 12);
    if (g.type === 4) return new three.SphereGeometry(1, 16, 12).scale(s[0], s[1], s[2]);
    if (g.type === 3) return new three.CylinderGeometry(s[0], s[0], 2 * (s[1] + s[0]), 16).rotateX(Math.PI / 2); // capsule, ends flat
    if (g.type === 5) return new three.CylinderGeometry(s[0], s[0], 2 * s[1], 24).rotateX(Math.PI / 2);
    if (g.type === 6) return new three.BoxGeometry(2 * s[0], 2 * s[1], 2 * s[2]);
    return null;
  }

  function build(meta, blob) {
    objects.forEach((o) => { scene.remove(o); o.material.dispose(); });
    objects = [];
    layers.robot = [];
    layers.scene = [];
    const shared = {};
    meta.geoms.forEach((g) => {
      let geometry = null;
      if (g.mesh !== undefined) {
        const m = meta.meshes[g.mesh];
        if (!shared[g.mesh]) {
          const geo = new three.BufferGeometry();
          geo.setAttribute("position", new three.BufferAttribute(new Float32Array(blob, m.vert_at, m.verts * 3), 3));
          geo.setIndex(new three.BufferAttribute(new Uint32Array(blob, m.face_at, m.faces * 3), 1));
          shared[g.mesh] = geo.toNonIndexed();
          shared[g.mesh].computeVertexNormals();
        }
        geometry = shared[g.mesh];
      } else {
        geometry = primitive(g);
      }
      if (!geometry) geometry = new three.BufferGeometry(); // keep state indices aligned
      const material = new three.MeshStandardMaterial({
        color: new three.Color(g.rgba[0], g.rgba[1], g.rgba[2]),
        transparent: g.rgba[3] < 1,
        opacity: g.rgba[3],
        side: three.DoubleSide,
        roughness: 0.8,
      });
      const mesh = new three.Mesh(geometry, material);
      mesh.matrixAutoUpdate = false;
      mesh.frustumCulled = false;
      scene.add(mesh);
      objects.push(mesh);
      (layers[g.layer] || layers.scene).push(mesh);
    });
    cam0 = (meta.cameras || {}).agentview || null;
    resetView();
    applyLayers();
  }

  function resetView() {
    if (!camera) return;
    if (cam0) {
      const x = cam0.xmat;
      camera.fov = cam0.fovy;
      camera.position.set(cam0.pos[0], cam0.pos[1], cam0.pos[2]);
      // MuJoCo camera: the third column of xmat is its backward axis, as in three.js. Up stays
      // world z for OrbitControls, which is exact while the camera has no roll (agentview has none).
      const back = new three.Vector3(x[2], x[5], x[8]);
      const target = camera.position.clone().addScaledVector(back, -1);
      controls.target.copy(target);
      camera.lookAt(target);
    } else {
      camera.position.set(1.6, -1.2, 1.2);
      controls.target.set(0, 0, 0.5);
    }
    camera.updateProjectionMatrix();
    controls.update();
    dirty = true;
  }

  function applyLayers() {
    const on = (id) => document.getElementById(id).checked;
    layers.robot.forEach((o) => { o.visible = on("mirror-robot"); });
    layers.scene.forEach((o) => { o.visible = on("mirror-scene"); });
    if (contacts) contacts.visible = on("mirror-contacts");
    dirty = true;
  }

  function applyState(buf) {
    const head = new DataView(buf);
    const step = head.getUint32(0, true), ncon = head.getUint32(4, true);
    const f = new Float32Array(buf, 8);
    contacts.geometry.setAttribute("position", new three.BufferAttribute(f.slice(0, ncon * 3), 3));
    let i = ncon * 3;
    for (const o of objects) {
      const e = o.matrix.elements;
      e[0] = f[i + 3]; e[4] = f[i + 4]; e[8] = f[i + 5]; e[12] = f[i];
      e[1] = f[i + 6]; e[5] = f[i + 7]; e[9] = f[i + 8]; e[13] = f[i + 1];
      e[2] = f[i + 9]; e[6] = f[i + 10]; e[10] = f[i + 11]; e[14] = f[i + 2];
      e[3] = 0; e[7] = 0; e[11] = 0; e[15] = 1;
      o.matrixWorldNeedsUpdate = true;
      i += 12;
    }
    dirty = true;
    box.dataset.step = step;
    box.dataset.contacts = ncon;
    note.textContent = `step ${step} · ${ncon} contact${ncon === 1 ? "" : "s"}`;
  }

  function poll() {
    if (busy || !status.active || !shown || !enabled || document.hidden || !status.mirror || !three) return;
    busy = true;
    const ready = status.mirror === modelId ? Promise.resolve() : Promise.all([
      fetch("/live/mirror/model.json").then((r) => r.json()),
      fetch("/live/mirror/model.bin").then((r) => r.arrayBuffer()),
    ]).then(([meta, blob]) => {
      if (meta.id !== status.mirror) throw new Error("model changed");
      build(meta, blob);
      modelId = meta.id;
    });
    ready.then(() => fetch("/live/mirror/state.bin"))
      .then((r) => { if (!r.ok) throw new Error("no state"); return r.arrayBuffer(); })
      .then(applyState)
      .catch(() => {})
      .finally(() => { busy = false; });
  }

  function sync() {
    const visible = shown && enabled && status.active;
    box.hidden = !visible;
    toggle.classList.toggle("on", enabled);
    if (!visible) return;
    if (!three) {
      note.textContent = "Loading the 3D viewer...";
      loadThree().then(resize).catch(() => { note.textContent = "The 3D viewer could not load (it needs cdnjs and jsDelivr)."; });
    } else if (!status.mirror) {
      note.textContent = "No simulator state yet.";
    }
    resize();
  }

  window.addEventListener("live-status", (e) => {
    status = e.detail.status;
    shown = e.detail.shown;
    if (!status.active) modelId = null;
    sync();
  });
  toggle.addEventListener("click", () => {
    enabled = !enabled;
    try { localStorage.setItem(PREF, enabled ? "1" : "0"); } catch (e) {}
    sync();
  });
  ["mirror-robot", "mirror-scene", "mirror-contacts"].forEach((id) => document.getElementById(id).addEventListener("change", applyLayers));
  document.getElementById("mirror-view").addEventListener("click", resetView);
  setInterval(poll, POLL_MS);
})();
