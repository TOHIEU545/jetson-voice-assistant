#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Rebuild M05 summary from an existing benchmark run."""

from __future__ import print_function

import argparse
import json
from pathlib import Path

from benchmark_model_noise import (
    CONFIGS,
    paired_effect,
    render_summary,
    summary_for_config,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    samples_path = run_dir / "samples.jsonl"

    if not samples_path.is_file():
        raise RuntimeError("samples.jsonl not found: %s" % samples_path)

    rows = []
    with samples_path.open("r") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))

    if not rows:
        raise RuntimeError("samples.jsonl is empty")

    metas = {}
    for key in CONFIGS:
        path = run_dir / key / "config_metadata.json"
        if not path.is_file():
            raise RuntimeError("Missing config metadata: %s" % path)
        metas[key] = json.loads(path.read_text())

    summary = {}
    for key in CONFIGS:
        subset = [row for row in rows if row["config"] == key]
        summary[key] = summary_for_config(subset, metas[key])

    effect = paired_effect(rows)

    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True)
    )
    (run_dir / "paired_effect.json").write_text(
        json.dumps(effect, indent=2, sort_keys=True)
    )

    text = render_summary(summary, effect)
    (run_dir / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
