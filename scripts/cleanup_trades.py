#!/usr/bin/env python3
"""
scripts/cleanup_trades.py

Safe cleanup utility for the trades database.

Features:
- Delete all rows in the trades table
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

- Delete rows by exit_time:
    python scripts/cleanup_trades.py --db trades_database.db --after 2025-07-01 --time-field exit_time --confirm

Notes:
- Dates are expected in ISO format: YYYY-MM-DD (time portion, if provided, will be ignored)
- The script defaults to db path 'trades_database.db' if not provided
"""

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
import sys

DEFAULT_DB = "trades_database.db"


def backup_db(db_path: Path) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.stem}_backup_{timestamp}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def build_where_clause(args):
    """
    Returns (where_clause_sql, params) or (None, None) if no filter (use --all)
    Use SQLite DATE() on ISO timestamp stored in entry_time/exit_time text columns.
    """
    tf = args.time_field
    if args.all:
        return None, None

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
        return None, None  # no filters -> treated like --all

    where = " AND ".join(f"({c})" for c in clauses)
    return where, params


def count_rows(conn: sqlite3.Connection, where_clause, params):
    cur = conn.cursor()
    if where_clause is None:
        q = "SELECT COUNT(*) FROM trades"
        cur.execute(q)
    else:
        q = f"SELECT COUNT(*) FROM trades WHERE {where_clause}"
        cur.execute(q, params)
    return cur.fetchone()[0]


def delete_rows(conn: sqlite3.Connection, where_clause, params):
    cur = conn.cursor()
    if where_clause is None:
        q = "DELETE FROM trades"
        cur.execute(q)
    else:
        q = f"DELETE FROM trades WHERE {where_clause}"
        cur.execute(q, params)
    conn.commit()
    return cur.rowcount


def parse_args():
    p = argparse.ArgumentParser(description="Cleanup trades database (SQLite).")
    p.add_argument("--db", default=DEFAULT_DB, help="Path to SQLite DB file (default: trades_database.db)")
    p.add_argument("--all", action="store_true", help="Delete all rows from trades table")
    p.add_argument("--time-field", choices=["entry_time", "exit_time"], default="entry_time",
                   help="Which timestamp column to use for date filters (default: entry_time)")
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

    where_clause, params = build_where_clause(args)

    # Connect readonly for dry-run count to be safe (we still open writable later)
    conn = sqlite3.connect(str(db_path))
    try:
        to_delete = count_rows(conn, where_clause, params)
    finally:
        conn.close()

    filter_desc = "ALL rows" if where_clause is None else f"rows matching filters on {args.time_field}"
    print(f"DB: {db_path}")
    print(f"Action: Delete {filter_desc}")
    print(f"Rows that would be deleted: {to_delete}")

    if args.dry_run:
        print("Dry-run mode: no changes made.")
        return

    if to_delete == 0:
        print("No rows to delete. Exiting.")
        return

    if not args.confirm:
        print("Not confirmed. Add --confirm to actually perform deletion.")
        return

    # Backup if requested
    if args.backup:
        backup_path = backup_db(db_path)
        print(f"Backup created: {backup_path}")

    # Proceed to delete
    conn = sqlite3.connect(str(db_path))
    try:
        deleted = delete_rows(conn, where_clause, params)
        print(f"Deleted rows: {deleted}")
        if args.vacuum:
            print("Running VACUUM...")
            conn.execute("VACUUM")
            print("VACUUM complete.")
    finally:
        conn.close()

    print("Done.")


if __name__ == "__main__":
    main()