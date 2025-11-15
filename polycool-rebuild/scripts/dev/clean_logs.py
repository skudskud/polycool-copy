#!/usr/bin/env python3
"""
Log cleaning and optimization script for Polycool services.

This script helps reduce log noise by:
1. Cleaning existing log files from repetitive entries
2. Providing recommendations for log level configuration
3. Showing log statistics

Usage:
    python scripts/dev/clean_logs.py [--dry-run] [--stats-only]
"""

import argparse
import gzip
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Log patterns to filter/clean
LOG_PATTERNS = {
    'sqlalchemy': [
        r'.*sqlalchemy\.engine\.Engine.*SELECT.*',
        r'.*sqlalchemy\.engine\.Engine.*BEGIN.*',
        r'.*sqlalchemy\.engine\.Engine.*COMMIT.*',
        r'.*sqlalchemy\.engine\.Engine.*INSERT.*',
        r'.*sqlalchemy\.engine\.Engine.*UPDATE.*',
        r'.*sqlalchemy\.engine\.Engine.*DELETE.*',
        r'.*sqlalchemy\.engine\.Engine.*\[cached.*',
        r'.*sqlalchemy\.engine\.Engine.*\[generated.*',
    ],
    'httpx': [
        r'.*httpx.*HTTP Request.*',
        r'.*httpx.*HTTP/.*200 OK.*',
    ],
    'web3_warnings': [
        r'.*pkg_resources is deprecated.*',
    ],
    'redis_connection': [
        r'.*🔌 Connecting to Redis.*',
        r'.*✅ Redis.*connected.*',
    ],
    'cache_operations': [
        r'.*🗑️ Cache invalidated.*',
    ],
    'notification_loops': [
        r'.*🔄 Notification processing loop.*',
    ],
    'websocket_reconnect': [
        r'.*✅ WebSocket connected.*',
        r'.*📡 Resending subscriptions.*',
    ]
}


class LogCleaner:
    """Clean and optimize log files"""

    def __init__(self, logs_dir: Path):
        self.logs_dir = logs_dir
        self.stats = defaultdict(Counter)

    def analyze_file(self, file_path: Path) -> Dict[str, int]:
        """Analyze a log file and return statistics"""
        if not file_path.exists():
            return {}

        file_stats = Counter()
        repetitive_lines = defaultdict(int)

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    # Count by category
                    for category, patterns in LOG_PATTERNS.items():
                        for pattern in patterns:
                            if re.search(pattern, line, re.IGNORECASE):
                                file_stats[category] += 1
                                repetitive_lines[line] += 1
                                break

                    # General stats
                    if 'ERROR' in line.upper():
                        file_stats['errors'] += 1
                    elif 'WARNING' in line.upper():
                        file_stats['warnings'] += 1
                    elif 'INFO' in line.upper():
                        file_stats['info'] += 1
                    elif 'DEBUG' in line.upper():
                        file_stats['debug'] += 1

        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return {}

        # Find most repetitive lines
        self.stats[file_path.name]['total_lines'] = line_num
        self.stats[file_path.name].update(file_stats)

        # Store top repetitive lines
        top_repetitive = sorted(repetitive_lines.items(), key=lambda x: x[1], reverse=True)[:10]
        self.stats[file_path.name]['top_repetitive'] = top_repetitive

        return dict(file_stats)

    def clean_file(self, file_path: Path, dry_run: bool = False) -> int:
        """Clean repetitive entries from a log file"""
        if not file_path.exists():
            return 0

        print(f"{'[DRY RUN] ' if dry_run else ''}Cleaning {file_path.name}...")

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

            original_count = len(lines)
            cleaned_lines = []
            seen_lines = defaultdict(int)

            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    cleaned_lines.append(line)
                    continue

                # Skip repetitive lines (more than 5 occurrences)
                should_skip = False
                for category, patterns in LOG_PATTERNS.items():
                    for pattern in patterns:
                        if re.search(pattern, line_stripped, re.IGNORECASE):
                            seen_lines[line_stripped] += 1
                            if seen_lines[line_stripped] > 5:
                                should_skip = True
                                break
                    if should_skip:
                        break

                if not should_skip:
                    cleaned_lines.append(line)

            removed_count = original_count - len(cleaned_lines)

            if not dry_run and removed_count > 0:
                # Create backup
                backup_path = file_path.with_suffix('.log.backup')
                if not backup_path.exists():
                    file_path.rename(backup_path)
                    print(f"  Backup created: {backup_path.name}")

                # Write cleaned version
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.writelines(cleaned_lines)

                print(f"  Removed {removed_count} repetitive lines")
            elif dry_run:
                print(f"  Would remove {removed_count} repetitive lines")

            return removed_count

        except Exception as e:
            print(f"Error cleaning {file_path}: {e}")
            return 0

    def print_stats(self):
        """Print log analysis statistics"""
        print("\n" + "="*80)
        print("LOG ANALYSIS STATISTICS")
        print("="*80)

        for filename, stats in self.stats.items():
            print(f"\n📄 {filename}:")
            print(f"  Total lines: {stats.get('total_lines', 0):,}")

            # Category breakdown
            categories = ['errors', 'warnings', 'info', 'debug', 'sqlalchemy', 'httpx',
                         'web3_warnings', 'redis_connection', 'cache_operations',
                         'notification_loops', 'websocket_reconnect']

            for category in categories:
                count = stats.get(category, 0)
                if count > 0:
                    print(f"  {category}: {count:,} lines")

            # Top repetitive lines
            if 'top_repetitive' in stats:
                print("  Most repetitive lines:")
                for line, count in stats['top_repetitive'][:5]:
                    if count > 3:  # Only show if repeated more than 3 times
                        truncated_line = line[:100] + "..." if len(line) > 100 else line
                        print(f"    {count}x: {truncated_line}")

    def truncate_old_logs(self, max_size_mb: int = 10, dry_run: bool = False):
        """Truncate log files that exceed maximum size"""
        max_size_bytes = max_size_mb * 1024 * 1024

        for log_file in self.logs_dir.glob("*.log"):
            try:
                size = log_file.stat().st_size
                if size > max_size_bytes:
                    size_mb = size / (1024 * 1024)
                    print(f"{'[DRY RUN] ' if dry_run else ''}Truncating {log_file.name} "
                          f"({size_mb:.1f}MB > {max_size_mb}MB)")

                    if not dry_run:
                        # Keep only the last 1000 lines
                        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                            lines = f.readlines()

                        if len(lines) > 1000:
                            # Create compressed backup
                            backup_path = log_file.with_suffix('.log.gz')
                            with gzip.open(backup_path, 'wt', encoding='utf-8') as f:
                                f.writelines(lines[:-1000])

                            # Keep only recent lines
                            with open(log_file, 'w', encoding='utf-8') as f:
                                f.writelines(lines[-1000:])

                            print(f"  Kept 1000 recent lines, compressed rest to {backup_path.name}")

            except Exception as e:
                print(f"Error processing {log_file}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Clean and optimize Polycool log files")
    parser.add_argument('--dry-run', action='store_true', help="Show what would be done without making changes")
    parser.add_argument('--stats-only', action='store_true', help="Only show statistics, don't clean")
    parser.add_argument('--truncate', type=int, default=10, help="Max log file size in MB (default: 10)")
    parser.add_argument('--logs-dir', type=Path, default=Path('logs'), help="Logs directory path")

    args = parser.parse_args()

    # Determine logs directory
    if args.logs_dir.is_absolute():
        logs_dir = args.logs_dir
    else:
        # Relative to project root
        project_root = Path(__file__).parent.parent.parent
        logs_dir = project_root / args.logs_dir

    if not logs_dir.exists():
        print(f"Logs directory not found: {logs_dir}")
        return 1

    cleaner = LogCleaner(logs_dir)

    print(f"Analyzing logs in: {logs_dir}")
    print(f"Dry run mode: {args.dry_run}")

    # Analyze all log files
    log_files = list(logs_dir.glob("*.log"))
    if not log_files:
        print("No log files found!")
        return 0

    for log_file in log_files:
        print(f"📊 Analyzing {log_file.name}...")
        cleaner.analyze_file(log_file)

    # Print statistics
    cleaner.print_stats()

    if args.stats_only:
        return 0

    # Clean files
    total_removed = 0
    for log_file in log_files:
        removed = cleaner.clean_file(log_file, args.dry_run)
        total_removed += removed

    # Truncate large files
    cleaner.truncate_old_logs(args.truncate, args.dry_run)

    print("\n✅ Log cleaning complete!")
    if not args.dry_run:
        print(f"Total repetitive lines removed: {total_removed}")

        print("\n📋 RECOMMENDATIONS:")
        print("1. The improved logging configuration will prevent future noise")
        print("2. Consider rotating logs daily for better performance")
        print("3. Monitor ERROR and WARNING levels more closely")
        print("4. Use log aggregation tools for production monitoring")

    return 0


if __name__ == "__main__":
    exit(main())
