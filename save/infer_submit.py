#!/usr/bin/env python3
"""
infer_submit.py

Submits a REDCap field‐type inference prompt (with map.json and report.json)
to the OpenAI API, handling multi‐chunk responses, stripping any Markdown
fences, parsing each chunk as JSON, concatenating them into a single JSON array,
and pretty‐printing the result.

Usage:
    python infer_submit.py [options]

Options:
    --model         Model name (default: gpt-4o-mini)
    --max-tokens    Max tokens for the completion (default: 2000)
    --chunks        Number of report.json chunks (1 = no split)
    --dry-run       Only calculate token usage; do not call the API
    --prompt        Path to prompt markdown file (default: infer_prompt.md)
    --reference     Path to REDCap definition markdown (default: redcap_reference.md)
    --map           Path to map.json (default: map.json)
    --report        Path to report.json (default: report.json)
    --config        Path to config JSON with {"api_key": "..."} (default: infer_config.json)
    --output        Path to write the concatenated JSON array (default: stdout)
    --log-level     Logging verbosity (default: info)
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

import httpx
import tiktoken
from openai import OpenAI
from quota_utils import summarize_usage

# ─── Model context windows ─────────────────────────────────────────────────────
MODEL_CONTEXT = {
    "gpt-4.1":        1_000_000,
    "gpt-4.1-mini":   1_000_000,
    "gpt-4.1-nano":   1_000_000,
    "gpt-4":          8_192,
    "gpt-4-32k":     32_768,
    "gpt-4o-mini":  128_000,
    "gpt-3.5-turbo": 16_384,
    "gpt-3.5-turbo-16k": 16_384,
}

def parse_args():
    p = argparse.ArgumentParser(
        description="Submit REDCap inference prompt to the OpenAI API"
    )
    p.add_argument("--model",
                   default="gpt-4o-mini",
                   help="Which model to call (default: %(default)s)")
    p.add_argument("--max-tokens",
                   type=int,
                   default=2000,
                   help="Max tokens for the model’s completion")
    p.add_argument("--chunks",
                   type=int,
                   default=1,
                   help="Number of report.json chunks (1 = no split)")
    p.add_argument("--dry-run",
                   action="store_true",
                   help="Only calculate & print token usage; don’t call the API")
    p.add_argument("--log-level",
                   choices=["debug", "info", "warning", "error", "critical"],
                   default="info",
                   help="Set logging verbosity")
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
                   help="Path to write the concatenated JSON array (default: stdout)")
    return p.parse_args()

def configure_logging(level: str):
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        level=lvl,
    )
    logging.getLogger("httpx").setLevel(lvl)
    logging.getLogger("openai").setLevel(lvl)
    os.environ["OPENAI_LOG"] = level

def load_files(args):
    paths = {
        "prompt":    Path(args.prompt),
        "reference": Path(args.reference),
        "map":       Path(args.map_file),
        "report":    Path(args.report),
        "config":    Path(args.config),
    }
    missing = [name for name, p in paths.items() if not p.is_file()]
    if missing:
        for name in missing:
            logging.error(f"{name} file not found: {paths[name]}")
        sys.exit(1)

    texts = {k: p.read_text(encoding="utf-8") for k, p in paths.items()}
    cfg = json.loads(texts.pop("config"))
    api_key = cfg.get("api_key")
    if not api_key:
        logging.error("‘api_key’ not found in config file")
        sys.exit(1)

    return texts["prompt"], texts["reference"], texts["map"], texts["report"], api_key

def make_http_client():
    def log_req(r: httpx.Request):
        size = len(r.content or b"")
        logging.debug(f"→ {r.method} {r.url}  body={size} bytes")

    def log_res(r: httpx.Response):
        length = r.headers.get("content-length") or "unknown"
        logging.debug(f"← {r.status_code} {r.reason_phrase}  body={length} bytes")

    return httpx.Client(
        event_hooks={"request": [log_req], "response": [log_res]}
    )

def count_tokens_for_model(model: str, *texts) -> int:
    enc = tiktoken.encoding_for_model(model)
    return sum(len(enc.encode(t)) for t in texts)

def report_budget(name, in_tokens, out_tokens, ctx_limit):
    total = in_tokens + out_tokens
    print(f"{name}: input={in_tokens}, max_output={out_tokens}, total_needed={total}, context={ctx_limit}")
    if total > ctx_limit:
        print("  ⚠️ WOULD EXCEED CONTEXT WINDOW!")
    else:
        print("  ✅ fits within context.")

def split_into_chunks(lst, n):
    if n <= 1:
        return [lst]
    size = -(-len(lst) // n)
    return [lst[i:i+size] for i in range(0, len(lst), size)]

def suggest_models(needed_tokens: int):
    candidates = [(name, ctx) for name, ctx in MODEL_CONTEXT.items() if ctx >= needed_tokens]
    if candidates:
        candidates.sort(key=lambda x: x[1])
        suggestions = ", ".join(f"{name} ({ctx} tokens)" for name, ctx in candidates)
        print(f"\nSuggestion: To handle {needed_tokens} tokens, consider one of: {suggestions}")
    else:
        print(f"\nNo available model can handle {needed_tokens} tokens. "
              "Consider reducing your prompt, increasing --chunks, or using a larger-context model.")

def strip_markdown_fences(text: str) -> str:
    """
    Remove leading/trailing triple-backtick fences (``` or ```json) from a block of text.
    """
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)

def check_and_report_budget(args, shared_in, report_in, report_text):
    ctx = MODEL_CONTEXT.get(args.model, 0)
    max_out = args.max_tokens

    if args.chunks <= 1:
        total_in = shared_in + report_in
        report_budget("FULL submission", total_in, max_out, ctx)
        if args.dry_run:
            sys.exit(0)
        if total_in + max_out > ctx:
            suggest_models(total_in + max_out)
            sys.exit(1)
    else:
        entries = json.loads(report_text)
        buckets = split_into_chunks(entries, args.chunks)
        worst = 0

        for idx, bucket in enumerate(buckets, start=1):
            bucket_json = json.dumps(bucket)
            in_tokens = shared_in + count_tokens_for_model(args.model, bucket_json)
            needed = in_tokens + max_out
            worst = max(worst, needed)

            mark = "✗" if needed > ctx else ""
            print(f"chunk {idx:3d}: input={in_tokens:5d} +{max_out:5d} = {needed:5d} {mark}")

        print(f"\nWorst-case: {worst} tokens; context = {ctx}")
        if args.dry_run:
            sys.exit(0)
        if worst > ctx:
            suggest_models(worst)
            sys.exit(1)

def build_shared_messages(prompt, reference, map_text):
    return [
        {"role": "system", "content": "You are ChatGPT, an expert assistant."},
        {"role": "user",   "content": prompt},
        {"role": "user",   "content": "### REDCap Reference:\n" + reference},
        {"role": "user",   "content": "### map.json:\n" + map_text},
    ]

def call_openai(client, model, messages, max_tokens):
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=max_tokens,
        )
    except Exception as e:
        err = str(e)
        if "insufficient_quota" in err or "429" in err:
            logging.error("OpenAI API quota exceeded.")
            try:
                start, end, usage = summarize_usage(client.api_key)
                logging.error(f"Usage from {start} to {end}: {usage}")
            except Exception as qe:
                logging.error(f"Additionally, failed to fetch usage summary: {qe}")
        else:
            logging.error(f"OpenAI API call failed: {e}")
        sys.exit(1)

    choice = resp.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        logging.warning(
            "Output truncated (finish_reason=length). Consider bumping max_tokens "
            "or using a larger-context model."
        )
    return choice.message.content

def process_submissions(args, client, prompt, reference, map_text, report_text):
    """
    For each chunk, strip fences, parse JSON, and collect into a single list.
    If any chunk fails JSON parsing, exit with an error.
    """
    entries = json.loads(report_text)
    shared = build_shared_messages(prompt, reference, map_text)
    combined = []

    for chunk in split_into_chunks(entries, args.chunks):
        body = json.dumps(chunk)
        msgs = shared + [
            {"role": "user", "content": "### report.json chunk:\n" + body},
        ]
        raw_output = call_openai(
            client=client,
            model=args.model,
            messages=msgs,
            max_tokens=args.max_tokens
        )
        clean_text = strip_markdown_fences(raw_output)
        try:
            parsed = json.loads(clean_text)
        except json.JSONDecodeError as e:
            logging.error("Failed to parse JSON from model response:")
            logging.error(clean_text)
            logging.error(f"JSONDecodeError: {e}")
            sys.exit(1)

        if not isinstance(parsed, list):
            logging.error("Expected a JSON array, but got:")
            logging.error(parsed)
            sys.exit(1)

        combined.extend(parsed)

    return combined

def main():
    args = parse_args()
    configure_logging(args.log_level)

    prompt, reference, map_text, report_text, api_key = load_files(args)
    client = OpenAI(api_key=api_key, http_client=make_http_client())

    shared_in = count_tokens_for_model(args.model, prompt, reference, map_text)
    report_in = count_tokens_for_model(args.model, report_text)

    check_and_report_budget(args, shared_in, report_in, report_text)

    combined_results = process_submissions(
        args, client, prompt, reference, map_text, report_text
    )

    # Pretty-print JSON output
    output_json = json.dumps(combined_results, indent=2)
    if args.output:
        Path(args.output).write_text(output_json, encoding="utf-8")
        print(f"Pretty-printed JSON output written to {args.output}")
    else:
        print(output_json)

if __name__ == "__main__":
    main()
