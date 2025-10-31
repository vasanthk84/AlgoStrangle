#!/usr/bin/env python3
"""
scripts/cleanup_trades.py

Safe cleanup utility for the trades database.
UPDATED: Now cleans both 'trades' and 'daily_performance' tables.

Features:
- Delete all rows in the 'trades' and 'daily_performance' tables
- Delete rows by date range (based on entry_time or exit_time)
- Dry-run to preview row counts before deletion
- Automatic backup of DB file before destructive operations
- Optional VACUUM to reclaim space after deletion

Usage examples:
- Preview all rows that would be deleted:
    python scripts/cleanup_trades.py --db trades_database.db --all --dry-run

- Delete everything (with backup):
    python scripts/cleanup_trades.py --db trades_database.db --all --confirm

- Preview rows with entry_time before 2025-10-01:
    python scripts/cleanup_trades.py --db trades_database.db --before 2025-10-01 --time-field entry_time --dry-run

- Delete rows with entry_time between two dates:
    python scripts/cleanup_trades.py --db trades_database.db --between 2025-01-01 2025-03-31 --time-field entry_time --confirm
"""

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
import sys
from typing import Tuple, List, Optional, Any

DEFAULT_DB = "trades_database.db"
TABLES_TO_CLEAN = ["trades", "daily_performance"]


def backup_db(db_path: Path) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.stem}_backup_{timestamp}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def build_where_clause(args: argparse.Namespace, table_name: str) -> Tuple[Optional[str], List[Any]]:
    """
    Returns (where_clause_sql, params) or (None, []) if no filter (use --all)
    Use SQLite DATE() on ISO timestamp stored in text columns.

    FIXED: Selects the correct date column based on the table name.
    """
    if args.all:
        return None, []

    # Determine the correct time/date column for the table
    if table_name == "trades":
        tf = args.time_field  # e.g., 'entry_time' or 'exit_time'
    elif table_name == "daily_performance":
        tf = "date"  # This table uses 'date'
    else:
        # Default fallback, though should not be hit
        tf = "entry_time"

    clauses = []
    params = []

    if args.before:
        clauses.append(f"date({tf}) <= date(?)")
        params.append(args.before)
    if args.after:
        clauses.append(f"date({tf}) >= date(?)")
        params.append(args.after)
    if args.between:
        start, end = args.between
        clauses.append(f"date({tf}) BETWEEN date(?) AND date(?)")
        params.extend([start, end])

    if not clauses:
        return None, []  # no filters -> treated like --all

    where = " AND ".join(f"({c})" for c in clauses)
    return where, params


def count_rows(conn: sqlite3.Connection, table_name: str, where_clause: Optional[str], params: List[Any]) -> int:
    """Counts rows in a specific table, optionally with a where clause."""
    cur = conn.cursor()
    if where_clause is None:
        q = f"SELECT COUNT(*) FROM {table_name}"
        cur.execute(q)
    else:
        q = f"SELECT COUNT(*) FROM {table_name} WHERE {where_clause}"
        cur.execute(q, params)
    return cur.fetchone()[0]


def delete_rows(conn: sqlite3.Connection, table_name: str, where_clause: Optional[str], params: List[Any]) -> int:
    """Deletes rows from a specific table, optionally with a where clause."""
    cur = conn.cursor()
    if where_clause is None:
        q = f"DELETE FROM {table_name}"
        cur.execute(q)
    else:
        q = f"DELETE FROM {table_name} WHERE {where_clause}"
        cur.execute(q, params)
    conn.commit()
    return cur.rowcount


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cleanup trades database (SQLite).")
    p.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite DB file (default: trades_database.db)")
    p.add_argument("--all", action="store_true", help="Delete all rows from all target tables")
    p.add_argument("--time-field", choices=["entry_time", "exit_time"], default="entry_time",
                   help="Which timestamp column to use for date filters on the 'trades' table (default: entry_time)")
    p.add_argument("--before", metavar="YYYY-MM-DD", help="Delete rows where date(time_field) <= this date")
    p.add_argument("--after", metavar="YYYY-MM-DD", help="Delete rows where date(time_field) >= this date")
    p.add_argument("--between", nargs=2, metavar=("START_DATE", "END_DATE"),
                   help="Delete rows where date(time_field) BETWEEN START_DATE AND END_DATE (inclusive)")
    p.add_argument("--dry-run", action="store_true", help="Only print how many rows would be deleted")
    p.add_argument("--confirm", action="store_true",
                   help="Perform deletion (must be provided to actually delete rows)")
    p.add_argument("--backup", action="store_true", default=True,
                   help="Backup DB file before deletion (default: True). Use --no-backup to disable.")
    p.add_argument("--no-backup", dest="backup", action="store_false",
                   help="Disable automatic backup before deletion")
    p.add_argument("--vacuum", action="store_true", help="Run VACUUM after deletion to reclaim space")
    return p.parse_args()


def main():
    args = parse_args()
    db_path = Path(args.db)

    if not db_path.exists():
        print(f"ERROR: DB file not found: {db_path}", file=sys.stderr)
        sys.exit(2)

    conn = sqlite3.connect(str(db_path))
    total_to_delete = 0
    counts_by_table = {}
    clauses_by_table = {}

    try:
        # First, count all rows to be deleted
        for table in TABLES_TO_CLEAN:
            where_clause, params = build_where_clause(args, table)

            try:
                to_delete = count_rows(conn, table, where_clause, params)
                counts_by_table[table] = to_delete
                clauses_by_table[table] = (where_clause, params)
                total_to_delete += to_delete
            except sqlite3.OperationalError as e:
                if f"no such column" in str(e):
                    print(
                        f"Warning: Column for filtering not found in table '{table}'. Assuming 0 rows to delete from it. Error: {e}")
                    counts_by_table[table] = 0
                    clauses_by_table[table] = (None, [])  # Set to no-op
                elif f"no such table: {table}" in str(e):
                    print(f"Info: Table '{table}' not found in database. Skipping.")
                    counts_by_table.pop(table, None)  # Remove from list
                else:
                    raise e
    finally:
        conn.close()

    # Determine if any filters were used
    is_filtered = not args.all and any(clauses_by_table.get(t, (None, []))[0] is not None for t in TABLES_TO_CLEAN)
    filter_desc = "rows matching filters" if is_filtered else "ALL rows"

    print(f"DB: {db_path}")
    print(f"Action: Delete {filter_desc} from tables: {', '.join(counts_by_table.keys())}")
    print("Rows that would be deleted:")

    for table, count in counts_by_table.items():
        print(f"  - {table}: {count} rows")
    print(f"  ---------------------")
    print(f"  - TOTAL: {total_to_delete} rows")

    if args.dry_run:
        print("\nDry-run mode: no changes made.")
        return

    if total_to_delete == 0:
        print("\nNo rows to delete. Exiting.")
        return

    if not args.confirm:
        print("\nNot confirmed. Add --confirm to actually perform deletion.")
        return

    # Backup if requested
    if args.backup:
        backup_path = backup_db(db_path)
        print(f"\nBackup created: {backup_path}")

    # Proceed to delete
    print("\nProceeding with deletion...")
    conn = sqlite3.connect(str(db_path))
    total_deleted = 0
    try:
        for table in counts_by_table.keys():
            if counts_by_table[table] > 0 or (not is_filtered and counts_by_table[table] == 0):
                where_clause, params = clauses_by_table[table]
                deleted = delete_rows(conn, table, where_clause, params)
                print(f"  - Deleted rows from {table}: {deleted}")
                total_deleted += deleted
            else:
                print(f"  - Skipping {table} (0 rows matched)")

        print(f"Total rows deleted: {total_deleted}")

        if args.vacuum:
            print("Running VACUUM...")
            conn.execute("VACUUM")
            print("VACUUM complete.")
    finally:
        conn.close()

    print("Done.")


if __name__ == "__main__":
    main()