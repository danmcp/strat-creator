#!/usr/bin/env python3
"""Retroactively add dry_run field to existing pipeline-data.json files.

One-time migration script. Marks runs as production or dry based on an
explicit list of production run IDs.

Usage:
    python3 scripts/patch-dry-run-field.py \
        --data-dir /path/to/RHAISTRAT \
        --production-runs 20260421-145725,20260421-153145,...
"""

import argparse
import json
import os
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(
        description="Add dry_run field to existing pipeline-data.json files")
    parser.add_argument("--data-dir", required=True,
                        help="Path to RHAISTRAT/ directory")
    parser.add_argument("--production-runs", required=True,
                        help="Comma-separated list of production run IDs")
    args = parser.parse_args()

    production = set(r.strip() for r in args.production_runs.split(",") if r.strip())
    print(f"Production runs: {sorted(production)}")

    patched = 0
    for entry in sorted(os.listdir(args.data_dir)):
        entry_path = os.path.join(args.data_dir, entry)
        if not os.path.isdir(entry_path) or os.path.islink(entry_path):
            continue
        try:
            datetime.strptime(entry, "%Y%m%d-%H%M%S")
        except ValueError:
            continue

        json_path = os.path.join(entry_path, "pipeline-data.json")
        if not os.path.exists(json_path):
            print(f"  {entry}: no pipeline-data.json, skipping")
            continue

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        is_dry = entry not in production
        old_value = data.get("dry_run")
        data["dry_run"] = is_dry

        ordered = {"generated_at": data.pop("generated_at", ""), "dry_run": is_dry}
        ordered.update(data)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(ordered, f, indent=2)

        status = "DRY" if is_dry else "PROD"
        changed = "" if old_value == is_dry else " (new)"
        print(f"  {entry}: {status}{changed}")
        patched += 1

    print(f"\nPatched {patched} run(s)")


if __name__ == "__main__":
    main()
