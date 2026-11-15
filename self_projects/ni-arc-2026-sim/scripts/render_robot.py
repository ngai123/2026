"""Quick offscreen render of the standalone robot for visual sanity check."""
from __future__ import annotations
import sys
from pathlib import Path
import mujoco
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
XML = ROOT / "mjcf" / "robot_diff.xml"
OUT_DIR = ROOT / "docs" / "screenshots"


def main() -> int:
    if not XML.exists():
        print(f"missing: {XML}", file=sys.stderr)
        return 2
    model = mujoco.MjModel.from_xml_path(str(XML))
    data = mujoco.MjData(model)
    for _ in range(200):
        mujoco.mj_step(model, data)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cam = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(model, cam)
    cam.type = mujoco.mjtCamera.mjCAMERA_FREE

    # Robot is at origin (or wherever build_robot.py placed it).
    cam.lookat[:] = (0.0, 0.0, 0.2)

    # Multiple angles.
    views = [
        ("robot_side.png",     {"distance": 1.5, "azimuth": 0.0,   "elevation": -10.0}),
        ("robot_front.png",    {"distance": 1.5, "azimuth": 90.0,  "elevation": -10.0}),
        ("robot_back.png",     {"distance": 1.5, "azimuth": -90.0, "elevation": -10.0}),
        ("robot_iso.png",      {"distance": 1.8, "azimuth": 45.0,  "elevation": -25.0}),
        ("robot_top.png",      {"distance": 2.0, "azimuth": 90.0,  "elevation": -85.0}),
    ]
    with mujoco.Renderer(model, width=960, height=540) as r:
        for fname, kw in views:
            for k, v in kw.items():
                setattr(cam, k, v)
            r.update_scene(data, camera=cam)
            arr = r.render().copy()
            out = OUT_DIR / fname
            Image.fromarray(arr).save(out)
            print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
