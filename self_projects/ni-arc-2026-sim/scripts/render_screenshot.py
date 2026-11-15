"""
render_screenshot.py — Render an offscreen image of the world for visual sanity check.

Run:   .venv/bin/python scripts/render_screenshot.py [--settle SECONDS] [--out PATH]
Output: PNG image (default: docs/screenshots/world_top.png + world_iso.png)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
WORLD = ROOT / "mjcf" / "world.xml"
OUT_DIR = ROOT / "docs" / "screenshots"


def render_named_cam(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    *,
    camera_name: str,
    width: int = 1280,
    height: int = 720,
) -> np.ndarray:
    cam_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, camera_name)
    if cam_id < 0:
        raise ValueError(f"camera '{camera_name}' not found in model")
    cam = mujoco.MjvCamera()
    cam.type = mujoco.mjtCamera.mjCAMERA_FIXED
    cam.fixedcamid = cam_id
    with mujoco.Renderer(model, width=width, height=height) as r:
        r.update_scene(data, camera=cam)
        return r.render().copy()


def save_png(arr: np.ndarray, path: Path) -> None:
    # Minimal PNG writer using only numpy + stdlib (no Pillow dep needed for this).
    try:
        from PIL import Image
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "Pillow"])
        from PIL import Image
    Image.fromarray(arr).save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=float, default=2.0,
                    help="seconds of physics to step before rendering")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    if not WORLD.exists():
        print(f"ERROR: {WORLD} not found. Run scripts/build_world.py first.", file=sys.stderr)
        return 2

    print(f"loading {WORLD}")
    model = mujoco.MjModel.from_xml_path(str(WORLD))
    data = mujoco.MjData(model)
    print(f"model: {model.nbody} bodies, {model.ngeom} geoms, dt={model.opt.timestep:.4f}s")

    if args.settle > 0:
        n_steps = int(args.settle / model.opt.timestep)
        print(f"settling {args.settle:.1f}s ({n_steps} steps)")
        for _ in range(n_steps):
            mujoco.mj_step(model, data)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    for cam_name, out_name in [
        ("cam_top",       "world_top.png"),
        ("cam_iso_sw",    "world_iso.png"),
        ("cam_blue_goal", "world_goal_blue.png"),
        ("cam_red_goal",  "world_goal_red.png"),
    ]:
        img = render_named_cam(model, data, camera_name=cam_name)
        out_path = args.out_dir / out_name
        save_png(img, out_path)
        print(f"wrote {out_path}  (camera: {cam_name})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
