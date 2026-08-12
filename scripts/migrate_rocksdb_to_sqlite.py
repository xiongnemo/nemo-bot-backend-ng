import os
import sys
import time
import sqlite3
import argparse
import logging
from collections import defaultdict

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Add parent directory to path so we can import from nemb-bot-backend-ng modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from rocksdict import Rdict, Options
except ImportError:
    logger.error("rocksdict is not installed. Please make sure you have it installed to read RocksDB.")
    sys.exit(1)

def migrate(dry_run=True, rocksdb_path="data/nemo_rocksdb", sqlite_path="data/nemo.sqlite"):
    if not os.path.exists(rocksdb_path):
        logger.error(f"RocksDB not found at {rocksdb_path}. Nothing to migrate.")
        return

    logger.info(f"Opening RocksDB at {rocksdb_path}...")
    try:
        db_rocks = Rdict(rocksdb_path, Options())
    except Exception as e:
        logger.error(f"Failed to open RocksDB: {e}")
        return

    stats = defaultdict(int)
    total = 0
    now = time.time()
    
    # We will buffer writes if we are not in dry-run mode
    records_to_insert = []

    for key, value in db_rocks.items():
        if not isinstance(key, bytes):
            key = str(key)
        else:
            key = key.decode("utf-8")
            
        parts = key.split(":", 2)
        if len(parts) != 3:
            logger.warning(f"Skipping malformed key: {key}")
            continue
            
        namespace, scope, k = parts
        stats[namespace] += 1
        total += 1
        
        if not isinstance(value, str):
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            else:
                value = str(value)
                
        records_to_insert.append((namespace, scope, k, value, now))

    logger.info("=== Migration Analysis (RocksDB -> SQLite) ===")
    logger.info(f"Total KV records found: {total}")
    for ns, count in stats.items():
        logger.info(f"  - Namespace '{ns}': {count} records")

    if dry_run:
        logger.info("\n[DRY RUN] No data was written to SQLite.")
        logger.info("Run this script with --execute to perform the actual migration.")
        return

    logger.info(f"\nWriting to SQLite at {sqlite_path}...")
    if not os.path.exists(sqlite_path):
        logger.warning(f"SQLite DB {sqlite_path} does not exist. It will be created, but are you sure this is the right path?")
        
    try:
        conn = sqlite3.connect(sqlite_path)
        # Ensure the table exists in case this is a fresh run (though it shouldn't be)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS kv (
            namespace   TEXT NOT NULL,
            scope       TEXT NOT NULL DEFAULT 'global',
            key         TEXT NOT NULL,
            value_json  TEXT NOT NULL,
            updated_at  REAL NOT NULL,
            PRIMARY KEY (namespace, scope, key)
        )
        """)
        
        cursor = conn.cursor()
        cursor.executemany(
            "INSERT OR REPLACE INTO kv (namespace, scope, key, value_json, updated_at) VALUES (?, ?, ?, ?, ?)",
            records_to_insert
        )
        conn.commit()
        conn.close()
        logger.info("[SUCCESS] All data has been successfully migrated to SQLite.")
    except Exception as e:
        logger.error(f"Failed to write to SQLite: {e}")
    finally:
        db_rocks.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate KV data from RocksDB back to SQLite")
    parser.add_argument("--execute", action="store_true", help="Perform the actual migration (defaults to Dry Run without this flag)")
    parser.add_argument("--rocksdb", type=str, default="data/nemo_rocksdb", help="Path to RocksDB directory")
    parser.add_argument("--sqlite", type=str, default="data/nemo.sqlite", help="Path to SQLite database file")
    
    args = parser.parse_args()
    migrate(dry_run=not args.execute, rocksdb_path=args.rocksdb, sqlite_path=args.sqlite)
