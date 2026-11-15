# 🛠️ Scripts

Standalone utility scripts. Run these from the **project root**, not from inside the `scripts/` folder.

---

## `test_mcp.py` — MCP Connectivity Test

Verifies that the MCP server is running and responding correctly. Calls `get_active_drones` and prints the raw SSE response.

**When to use:** After starting `main.py`, to confirm the MCP server on port 8766 is healthy before running any agents.

```bash
# Start the MCP server first
python main.py --models gemini-2.5-flash &

# Then in a second terminal:
python scripts/test_mcp.py
```

**Expected output:**
```
Raw response: meta=None content=[TextContent(type='text', text='["drone_21","drone_22","drone_23","drone_24","drone_25"]')]
Texts: ['["drone_21","drone_22","drone_23","drone_24","drone_25"]']
```

**Error output (server not running):**
```
ConnectionRefusedError: [Errno 61] Connection refused
→ Make sure main.py is running and the MCP server has started (wait ~5s after launch)
```

---

## `view_db.py` — Database Inspector

Prints the contents of `rescue_mission.db` in tabular form — up to 10 rows per table, with a total row count.

**When to use:** After running a mission, to inspect what was recorded in the persistent SQLite database.

```bash
python scripts/view_db.py
```

**Example output:**
```
=== RESCUE MISSION DATABASE EXAMINER ===

--- TABLE: MISSION_LOG ---
 id  tick  drone_id   event_type    message                         timestamp
  1   12   drone_21   scan          Scanned (120.981, 14.591)       1742476800.1
  2   18   drone_22   rescue        Rescued survivor at (120.975)   1742476812.4
... and 47 more rows.

--- TABLE: SCANNED_AREAS ---
 id  drone_id    x          y        radius  tick   timestamp
  1  drone_21   120.981   14.591    0.1      12    1742476800.1
... and 203 more rows.

--- TABLE: SURVIVORS ---
 id    x          y        is_critical  is_rescued  discovered_by   timestamp
  1   120.975   14.605    True         True        drone_21        1742476812.4
... and 8 more rows.
```

**Tables:**

| Table | Contains |
|-------|---------|
| `mission_log` | All tick events — scans, rescues, battery swaps |
| `scanned_areas` | Every `thermal_scan` call with GPS coordinates and radius |
| `survivors` | Discovered survivors with rescue status |

> The database file `rescue_mission.db` is created in the project root when the simulation first runs. It persists across restarts — delete it manually to start a clean mission.
