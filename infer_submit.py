#!/usr/bin/env python3
"""
infer_submit.py

Reads prompt, reference, map, report, and config files, assembles an OpenAI
chat completion request using the v1.x SDK, and outputs the DSL transformation
script. On quota errors, prints a usage summary via quota_utils.
"""

import argparse
import json
import sys
from pathlib import Path
from quota_utils import summarize_usage

from openai import OpenAI

def parse_args():
    p = argparse.ArgumentParser(
        description="Submit REDCap inference prompt to the OpenAI API"
    )
    p.add_argument("--prompt",    default="infer_prompt.md",
                   help="Path to the user prompt markdown file")
    p.add_argument("--reference", default="redcap_reference.md",
                   help="Path to the REDCap definition markdown file")
    p.add_argument("--map", dest="map_file", default="map.json",
                   help="Path to map.json")
    p.add_argument("--report",    default="report.json",
                   help="Path to report.json")
    p.add_argument("--config",    default="infer_config.json",
                   help="Path to config JSON containing {\"api_key\": \"...\"}")
    p.add_argument("--output",
                   help="Path to write the model's output (default: stdout)")
    return p.parse_args()

def main():
    args = parse_args()

    # Collect and validate file paths
    files = {
        "prompt":   Path(args.prompt),
        "reference":Path(args.reference),
        "map":      Path(args.map_file),
        "report":   Path(args.report),
        "config":   Path(args.config),
    }
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        for name in missing:
            print(f"ERROR: {name} file not found: {files[name]}", file=sys.stderr)
        sys.exit(1)

    # Load API key from config file
    cfg = json.loads(files["config"].read_text(encoding="utf-8"))
    api_key = cfg.get("api_key")
    if not api_key:
        print("ERROR: 'api_key' not found in config file", file=sys.stderr)
        sys.exit(1)

    # Read inputs
    prompt_text    = files["prompt"].read_text(encoding="utf-8")
    reference_text = files["reference"].read_text(encoding="utf-8")
    map_text       = files["map"].read_text(encoding="utf-8")
    report_text    = files["report"].read_text(encoding="utf-8")

    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)

    # Build chat messages
    messages = [
        {"role":"system",
         "content":"You are ChatGPT, an expert assistant. Follow the user's prompt."},
        {"role":"user", "content": prompt_text},
        {"role":"user", "content": "### REDCap Reference:\n" + reference_text},
        {"role":"user", "content": "### map.json:\n" + map_text},
        {"role":"user", "content": "### report.json:\n" + report_text},
    ]

    # Call ChatCompletion and handle errors
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
            max_tokens=2000,
        )
    except Exception as e:
        err = str(e)
        if "insufficient_quota" in err or "429" in err:
            print("ERROR: OpenAI API quota exceeded.", file=sys.stderr)
            try:
                start, end, usage = summarize_usage(api_key=api_key)
                print(f"Usage from {start} to {end}:", file=sys.stderr)
                for model, tokens in usage.items():
                    print(f"  {model}: {tokens} tokens", file=sys.stderr)
            except Exception as qe:
                # print the real quota‐query error so you can see what’s going on
                print("Additionally, failed to fetch usage summary:", qe, file=sys.stderr)
        else:
            print(f"ERROR: OpenAI API call failed: {e}", file=sys.stderr)
        sys.exit(1)

    dsl_output = response.choices[0].message.content

    # Output the DSL script
    if args.output:
        Path(args.output).write_text(dsl_output, encoding="utf-8")
        print(f"DSL script written to {args.output}")
    else:
        print(dsl_output)

if __name__ == "__main__":
    main()
