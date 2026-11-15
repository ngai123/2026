import sqlite3
import os
import time
import math
import json

DB_FILE = "rescue_mission.db"

def init_db():
    """Initialize the SQLite database schema if it doesn't exist."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Mission Log
    c.execute('''
        CREATE TABLE IF NOT EXISTS mission_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tick INTEGER,
            drone_id TEXT,
            event_type TEXT,
            message TEXT,
            timestamp REAL
        )
    ''')
    
    # Scanned Areas (Tracking specific coordinate + radius pairs)
    c.execute('''
        CREATE TABLE IF NOT EXISTS scanned_areas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drone_id TEXT,
            x REAL,
            y REAL,
            radius REAL,
            tick INTEGER,
            timestamp REAL
        )
    ''')
    
    # Survivors Discovered
    c.execute('''
        CREATE TABLE IF NOT EXISTS survivors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            x REAL,
            y REAL,
            is_critical BOOLEAN,
            is_rescued BOOLEAN,
            discovered_by TEXT,
            timestamp REAL
        )
    ''')

    # Chain-of-thought traces + summarizer output (persistent record of AI reasoning)
    c.execute('''
        CREATE TABLE IF NOT EXISTS thought_processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            drone_id TEXT,
            round_num INTEGER,
            original_text TEXT,
            summary_text TEXT,
            model_name TEXT,
            duration_ms INTEGER,
            timestamp REAL
        )
    ''')

    conn.commit()
    conn.close()

def log_event(tick: int, drone_id: str, event_type: str, message: str):
    """Save an event to the mission log."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO mission_log (tick, drone_id, event_type, message, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (tick, drone_id, event_type, message, time.time()))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error logging event: {e}")
    finally:
        conn.close()

def record_scan(drone_id: str, x: float, y: float, radius: float, tick: int):
    """Commit a 2D spatial scan to the persistent tracker."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO scanned_areas (drone_id, x, y, radius, tick, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (drone_id, x, y, radius, tick, time.time()))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error recording scan: {e}")
    finally:
        conn.close()

def get_scanned_areas_summary() -> str:
    """Read all scans from SQLite and cluster them into a readable summary.
    This prevents prompt bloat while giving Drones + Commander awareness
    of previously cleared regions."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT x, y, radius FROM scanned_areas")
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            return "No areas scanned yet."
            
        # Very simple clustering: round coords to 2 decimals (~1.1km boxes)
        clusters = {}
        for r in rows:
            rx = round(r[0], 2)
            ry = round(r[1], 2)
            key = (rx, ry)
            clusters[key] = clusters.get(key, 0) + 1
            
        summary_lines = []
        for (rx, ry), overlaps in clusters.items():
            summary_lines.append(f"Region roughly centered at (x={rx:.2f}, y={ry:.2f}) scanned {overlaps} times.")
            
        return json.dumps({
            "status": "partial_map",
            "clusters": summary_lines,
            "instruction": "Avoid routing drones to these center coordinates as they are already mapped."
        })
    except Exception as e:
        return json.dumps({"error": f"DB Failure: {e}"})

def record_thought_process(drone_id: str, round_num: int, original_text: str,
                            summary_text: str, model_name: str, duration_ms: int) -> None:
    """Persist a drone's chain-of-thought trace together with its summarized form."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            INSERT INTO thought_processes
                (drone_id, round_num, original_text, summary_text, model_name, duration_ms, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (drone_id, round_num, original_text, summary_text, model_name, duration_ms, time.time()))
        conn.commit()
    except Exception as e:
        print(f"[DB] Error recording thought process: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def record_survivor(x: float, y: float, is_critical: bool, discovered_by: str, is_rescued: bool = False):
    """Mark a survivor permanently in the database if not already present."""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Check if survivor reasonably exists at this coord
        c.execute('''
            SELECT id FROM survivors 
            WHERE abs(x - ?) < 0.001 AND abs(y - ?) < 0.001
        ''', (x, y))
        
        existing = c.fetchone()
        if not existing:
            c.execute('''
                INSERT INTO survivors (x, y, is_critical, is_rescued, discovered_by, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (x, y, is_critical, is_rescued, discovered_by, time.time()))
            conn.commit()
    except Exception as e:
        print(f"[DB] Error recording survivor: {e}")
    finally:
        conn.close()

# Auto-initialize on import
try:
    init_db()
except Exception as e:
    print(f"[DB] Init Error: {e}")
