import sqlite3
import pandas as pd
import sys

DB_FILE = "rescue_mission.db"

def main():
    print("=== RESCUE MISSION DATABASE EXAMINER ===\n")
    try:
        conn = sqlite3.connect(DB_FILE)
    except Exception as e:
        print(f"Could not connect to {DB_FILE}: {e}")
        sys.exit(1)
        
    tables = ["mission_log", "scanned_areas", "survivors"]
    
    for table in tables:
        print(f"--- TABLE: {table.upper()} ---")
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table} LIMIT 10", conn)
            if df.empty:
                print("(Empty)\n")
            else:
                print(df.to_string(index=False))
                
            # Count total
            c = conn.cursor()
            c.execute(f"SELECT COUNT(*) FROM {table}")
            count = c.fetchone()[0]
            if count > 10:
                print(f"... and {count - 10} more rows.\n")
            else:
                print("\n")
                
        except Exception as e:
            print(f"(Error reading table: {e})\n")
            
    conn.close()

if __name__ == "__main__":
    main()
