#!/usr/bin/env python3
"""
summarize_rcm.py

Driver that invokes llm_submit.py for a sequence of *.rcm files, then feeds
the stage summaries into a roll-up prompt to create a single pipeline report.

Usage example:

    python summarize_rcm.py stage1.rcm stage2.rcm \
      --config job_summary.json --output combined-summary.md

Each *.rcm file is processed in order, reusing the existing llm_submit
pipeline so that per-stage summaries stay within model context limits. The
resulting stage summaries are then supplied to a roll-up prompt that produces a
single consolidated report.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = (SCRIPT_DIR / "job_summary.json").resolve()
DEFAULT_ROLLUP_CONFIG = (SCRIPT_DIR / "job_summary_rollup.json").resolve()
DEFAULT_OUTPUT_NAME = "combined-summary.md"


def invoke_llm_submit(
    config: Path,
    source_path: Path,
    io_dir: Path | None,
    key_file: Path | None,
    label: str,
) -> Tuple[str, Path, str]:
    """Invoke llm_submit.py and return (label, output_path, contents)."""

    llm_submit = Path(__file__).with_name("llm_submit.py")
    if not llm_submit.is_file():
        raise SystemExit(f"ERROR: llm_submit.py not found at {llm_submit}")

    cmd: List[str] = [
        sys.executable,
        str(llm_submit),
        "--config",
        str(config),
        "--source",
        str(source_path),
    ]
    if io_dir is not None:
        cmd.extend(["--io-dir", str(io_dir)])
    if key_file is not None:
        cmd.extend(["--key-file", str(key_file)])

    print(f"→ Summarising {label} …", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, end="", file=sys.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"ERROR: llm_submit failed for {label} (exit {proc.returncode})")

    match = re.search(r"Wrote combined output to\s+(.+)$", proc.stdout, re.MULTILINE)
    if not match:
        raise SystemExit(
            "ERROR: Unable to determine llm_submit output path. "
            "Ensure the command completed successfully."
        )

    out_path = Path(match.group(1).strip())
    if not out_path.is_file():
        raise SystemExit(f"ERROR: Expected summary file not found: {out_path}")

    return label, out_path, out_path.read_text(encoding="utf-8")


def build_rollup_input(summaries: List[Tuple[str, Path, str]]) -> str:
    lines: List[str] = []
    for idx, (label, _, content) in enumerate(summaries, start=1):
        lines.append(f"### Stage {idx}: {label}")
        lines.append("")
        lines.append(content.rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an aggregated summary for multiple RCM files."
    )
    parser.add_argument(
        "rcm_files",
        nargs="+",
        help="Paths to *.rcm files in the order they should be summarised",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG,
        help="Path to llm_submit job config (default: job_summary.json)",
    )
    parser.add_argument(
        "--rollup-config",
        default=DEFAULT_ROLLUP_CONFIG,
        help="Path to llm_submit job config for the rollup stage (default: job_summary_rollup.json)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Path for the combined markdown summary (default: combined-summary.md)",
    )
    parser.add_argument(
        "--io-dir",
        help="Override llm_submit --io-dir (defaults to current working directory)",
    )
    parser.add_argument(
        "--key-file",
        help="Path to OpenAI API key file to pass through to llm_submit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config_path = Path(args.config).resolve()
    if not config_path.is_file():
        raise SystemExit(f"ERROR: config file not found: {config_path}")

    rollup_config_path = Path(args.rollup_config).resolve()
    if not rollup_config_path.is_file():
        raise SystemExit(f"ERROR: rollup config file not found: {rollup_config_path}")

    io_dir = Path(args.io_dir).resolve() if args.io_dir else None
    key_file = Path(args.key_file).resolve() if args.key_file else None
    if key_file is not None and not key_file.is_file():
        raise SystemExit(f"ERROR: key file not found: {key_file}")

    summaries: List[Tuple[str, Path, str]] = []
    for rcm in args.rcm_files:
        rcm_path = Path(rcm)
        if not rcm_path.is_absolute():
            if io_dir is not None:
                rcm_path = (io_dir / rcm_path).resolve()
            else:
                rcm_path = rcm_path.resolve()
        if not rcm_path.is_file():
            raise SystemExit(f"ERROR: RCM file not found: {rcm_path}")
        summaries.append(
            invoke_llm_submit(config_path, rcm_path, io_dir, key_file, rcm_path.name)
        )

    rollup_input = build_rollup_input(summaries)

    with tempfile.NamedTemporaryFile(delete=False, suffix="-stages.md") as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(rollup_input.encode("utf-8"))

    try:
        _, rollup_out_path, rollup_content = invoke_llm_submit(
            rollup_config_path,
            tmp_path,
            io_dir,
            key_file,
            "rollup",
        )
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass

    if args.output:
        output_path = Path(args.output).resolve()
    elif io_dir is not None:
        output_path = (io_dir / DEFAULT_OUTPUT_NAME).resolve()
    else:
        output_path = Path(DEFAULT_OUTPUT_NAME).resolve()
    output_path.write_text(rollup_content, encoding="utf-8")
    print(f"Rollup summary written to {output_path}")
    print(f"Rollup source: {rollup_out_path}")


if __name__ == "__main__":
    main()
