"""Clear proxy logs and Dashboard history.

Usage:
    python scripts/clear_history.py
    python scripts/clear_history.py --logs-only
    python scripts/clear_history.py --keep-cache
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import ACCESS_LOG_PATH, DATABASE_PATH, ERROR_LOG_PATH, LOG_DIR  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="清理代理服务器历史日志和 Dashboard 统计记录")
    parser.add_argument(
        "--logs-only",
        action="store_true",
        help="只清理 logs 目录下的日志文件，不修改数据库",
    )
    parser.add_argument(
        "--db-only",
        action="store_true",
        help="只清理 SQLite 数据库历史，不清理日志文件",
    )
    parser.add_argument(
        "--keep-cache",
        action="store_true",
        help="保留 cache_records，只清理 access_logs 和日志文件",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要清理的内容，不实际删除",
    )
    return parser.parse_args()


def truncate_file(path: Path, dry_run: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        print(f"[dry-run] truncate file: {path}")
        return
    path.write_text("", encoding="utf-8")
    print(f"cleared file: {path}")


def clear_log_files(dry_run: bool) -> None:
    log_dir = Path(LOG_DIR)
    targets = {
        Path(ACCESS_LOG_PATH),
        Path(ERROR_LOG_PATH),
        log_dir / "stats.json",
        log_dir / "top_resources.json",
    }

    for path in sorted(targets):
        if path.exists() or path.suffix == ".log":
            truncate_file(path, dry_run)


def clear_database(keep_cache: bool, dry_run: bool) -> None:
    db_path = Path(DATABASE_PATH)
    if not db_path.exists():
        print(f"database not found, skipped: {db_path}")
        return

    statements = ["DELETE FROM access_logs"]
    if not keep_cache:
        statements.append("DELETE FROM cache_records")

    if dry_run:
        print(f"[dry-run] database: {db_path}")
        for statement in statements:
            print(f"[dry-run] execute: {statement}")
        return

    with sqlite3.connect(db_path) as conn:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
        conn.execute("VACUUM")

    cleared = "access_logs"
    if not keep_cache:
        cleared += ", cache_records"
    print(f"cleared database tables: {cleared}")


def main() -> None:
    args = parse_args()
    if args.logs_only and args.db_only:
        raise SystemExit("--logs-only and --db-only cannot be used together")

    if not args.db_only:
        clear_log_files(args.dry_run)

    if not args.logs_only:
        clear_database(keep_cache=args.keep_cache, dry_run=args.dry_run)

    print("history cleanup finished")


if __name__ == "__main__":
    main()
