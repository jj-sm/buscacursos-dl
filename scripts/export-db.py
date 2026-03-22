#!/usr/bin/env python3

import argparse
import csv
import json
import sqlite3
from pathlib import Path


def get_table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [row[0] for row in rows]


def dump_table(conn: sqlite3.Connection, table: str) -> list[dict]:
    cursor = conn.execute(f'SELECT * FROM "{table}"')
    columns = [desc[0] for desc in cursor.description or []]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def export_json(conn: sqlite3.Connection, tables: list[str], output_path: Path) -> None:
    payload = {table: dump_table(conn, table) for table in tables}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False)


def export_csv(conn: sqlite3.Connection, tables: list[str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    for table in tables:
        rows = dump_table(conn, table)
        output_path = output_dir / f"{table}.csv"

        if not rows:
            # Keep a valid empty CSV file for empty tables.
            output_path.write_text("", encoding="utf-8")
            continue

        with output_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export an SQLite database to JSON or CSV."
    )
    parser.add_argument("db_path", help="Path to SQLite database file")
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Export format (default: json)",
    )
    parser.add_argument(
        "--output",
        help="Output file path for JSON, or output directory for CSV",
    )
    parser.add_argument(
        "--table",
        help="Export only one table (default: export all tables)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)

    if not db_path.exists():
        raise SystemExit(f"Database file not found: {db_path}")

    if args.format == "json":
        output = Path(args.output) if args.output else Path("dump.json")
    else:
        output = Path(args.output) if args.output else Path("dump_csv")

    with sqlite3.connect(db_path) as conn:
        tables = get_table_names(conn)

        if args.table:
            if args.table not in tables:
                raise SystemExit(f"Table not found: {args.table}")
            tables = [args.table]

        if not tables:
            raise SystemExit("No user tables found in database")

        if args.format == "json":
            export_json(conn, tables, output)
        else:
            export_csv(conn, tables, output)


if __name__ == "__main__":
    main()
