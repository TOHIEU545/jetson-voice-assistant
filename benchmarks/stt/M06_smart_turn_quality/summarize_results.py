#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Rebuild M06 summary from an existing benchmark run."""

from __future__ import print_function

import argparse
import json
from pathlib import Path

from benchmark_smart_turn import (
    CONFIG_KEY,
    render_summary,
    summary_for_config,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    args = ap.parse_args()

    run_dir = Path(
        args.run_dir
    ).resolve()

    samples_path = (
        run_dir
        / "samples.jsonl"
    )

    if not samples_path.is_file():
        raise RuntimeError(
            "samples.jsonl not found: %s"
            % samples_path
        )

    rows = []

    with samples_path.open("r") as f:
        for line in f:
            if line.strip():
                rows.append(
                    json.loads(line)
                )

    if not rows:
        raise RuntimeError(
            "samples.jsonl is empty"
        )

    meta_path = (
        run_dir
        / CONFIG_KEY
        / "config_metadata.json"
    )

    if not meta_path.is_file():
        raise RuntimeError(
            "Missing config metadata: %s"
            % meta_path
        )

    meta = json.loads(
        meta_path.read_text()
    )

    summary = {
        CONFIG_KEY:
            summary_for_config(
                rows,
                meta,
            )
    }

    (
        run_dir
        / "summary.json"
    ).write_text(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )

    text = render_summary(
        summary
    )

    (
        run_dir
        / "summary.md"
    ).write_text(text)

    print(text)


if __name__ == "__main__":
    main()
