"""
run_viewer.py — Open the generated MuJoCo world in the interactive viewer.

Run:   .venv/bin/python scripts/run_viewer.py
Controls (standard MuJoCo viewer):
  Right-drag : rotate camera
  Left-drag  : translate camera
  Scroll     : zoom
  Double-click a body: select
  Ctrl + drag selected body: move it
  Space      : pause / unpause physics
  H          : toggle help overlay
"""
from __future__ import annotations

import sys
from pathlib import Path

import mujoco
import mujoco.viewer

ROOT = Path(__file__).resolve().parent.parent
WORLD = ROOT / "mjcf" / "world.xml"


def main() -> int:
    if not WORLD.exists():
        print(f"ERROR: {WORLD} not found. Run scripts/build_world.py first.", file=sys.stderr)
        return 2
    print(f"loading {WORLD}")
    model = mujoco.MjModel.from_xml_path(str(WORLD))
    data = mujoco.MjData(model)
    print(f"model has {model.nbody} bodies, {model.ngeom} geoms, "
          f"{model.nq} dofs, dt={model.opt.timestep:.4f}s")
    mujoco.viewer.launch(model, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
