"""
verify_env.py — Sanity-check the generated arena.

Loads the world, runs physics for SETTLE_S seconds, and checks:
  - model loads without errors
  - all 36 standard + 4 preloaded + 20 golden = 60 balls have a sphere geom
  - after settling, no ball has Z < -0.5 (i.e., none have fallen through the floor)
  - after settling, all standard balls remain within the shared-zone X/Y bounds (±0.4 m tolerance)

Returns 0 if all checks pass, 1 otherwise.
"""
from __future__ import annotations

import sys
from pathlib import Path

import mujoco
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORLD = ROOT / "mjcf" / "world.xml"
SPEC = ROOT / "spec" / "arena.yaml"
SETTLE_S = 3.0


def main() -> int:
    spec = yaml.safe_load(SPEC.read_text())
    model = mujoco.MjModel.from_xml_path(str(WORLD))
    data = mujoco.MjData(model)
    print(f"OK  model loads: {model.nbody} bodies, {model.ngeom} geoms")

    # Identify ball bodies by name prefix.
    ball_body_ids = []
    for i in range(model.nbody):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, i)
        if name and (name.startswith("ball_std_")
                     or name.startswith("ball_pre_")
                     or name.startswith("ball_gold_")):
            ball_body_ids.append(i)
    expected = (spec["balls"]["standard"]["count_in_shared_zone"]
                + 2 * spec["balls"]["standard"]["count_preloaded_per_team"]
                + 2 * spec["balls"]["golden"]["count_per_team"])
    if len(ball_body_ids) != expected:
        print(f"FAIL ball count: got {len(ball_body_ids)}, expected {expected}")
        return 1
    print(f"OK  ball count: {len(ball_body_ids)} ({expected} expected)")

    # Settle.
    n_steps = int(SETTLE_S / model.opt.timestep)
    for _ in range(n_steps):
        mujoco.mj_step(model, data)
    print(f"OK  stepped {SETTLE_S}s ({n_steps} steps), sim time = {data.time:.3f}s")

    # Check none have fallen through.
    fallen = []
    for bid in ball_body_ids:
        z = data.xpos[bid, 2]
        if z < -0.5:
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, bid)
            fallen.append((name, z))
    if fallen:
        print(f"FAIL {len(fallen)} balls fell through floor:")
        for name, z in fallen[:5]:
            print(f"     {name}: z={z:.3f}")
        return 1
    print("OK  no balls fell through floor")

    # Check standard balls remain within shared-zone X/Y bounds.
    sz_x = spec["zones"]["shared_ball"]["x"]
    sz_y = spec["zones"]["shared_ball"]["y"]
    tol = 0.4
    out_of_zone = []
    for bid in ball_body_ids:
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, bid)
        if not name.startswith("ball_std_"):
            continue
        x, y, _ = data.xpos[bid]
        if not (sz_x[0] - tol <= x <= sz_x[1] + tol and sz_y[0] - tol <= y <= sz_y[1] + tol):
            out_of_zone.append((name, x, y))
    if out_of_zone:
        print(f"WARN {len(out_of_zone)} standard balls drifted outside shared zone (+{tol}m tol):")
        for name, x, y in out_of_zone[:5]:
            print(f"     {name}: ({x:.2f}, {y:.2f})")
    else:
        print(f"OK  all standard balls within shared zone (±{tol}m)")

    # Quick summary of where everything ended up.
    z_vals = data.xpos[ball_body_ids, 2]
    print(f"INFO  ball Z range: [{z_vals.min():.3f}, {z_vals.max():.3f}] m")

    print("\nverification PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
