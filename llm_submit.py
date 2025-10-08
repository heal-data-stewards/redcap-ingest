#!/usr/bin/env python3
"""
llm_submit.py – OpenAI submission helper
(auto-chunking, io-dir, CLI source; consistent input/output types)

Changes in this build:
- Consistent type names:
  * Input:  source_format ∈ {"json","text","lines"}
  * Output: output.format ∈ {"json","text"}   (no "raw")
- Behavior is derived from output.format only:
  * "json" → parse each response chunk as JSON and concat arrays
  * "text" → treat responses as plain text and concatenate with blank lines
- Source path is CLI-only: --source PATH (always a file). Format comes
  from config via "source_format".
- Auto-chunking is internal; configs cannot specify chunk counts.
- --io-dir prefixes relative --source and rendered output.path_template.
- Output templates can use {srcbase} and {srcstem}.
"""
import argparse, json, logging, os, sys, time, uuid
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # optional for YAML configs
except Exception:
    yaml = None

import httpx
import tiktoken
from openai import OpenAI, BadRequestError

MAX_ROWS_PER_CHUNK = 60

MODEL_CONTEXT = {
    "gpt-4.1":        1_000_000,
    "gpt-4.1-mini":   1_000_000,
    "gpt-4.1-nano":   1_000_000,
    "gpt-4o":           128_000,
    "gpt-4o-mini":      128_000,
    "o4":              200_000,
    "o4-mini":         200_000,
    "gpt-4":              8_192,
    "gpt-4-32k":        32_768,
    "gpt-3.5-turbo":     16_384,
}

MODEL_COMPLETION_LIMIT = {
    "gpt-4.1": 32_768,
    "gpt-4.1-mini": 32_768,
    "gpt-4.1-nano": 32_768,
    "gpt-4o": 16_384,
    "gpt-4o-mini": 16_384,
    "o4": 32_768,
    "o4-mini": 32_768,
    "gpt-4": 8_192,
    "gpt-4-32k": 32_768,
    "gpt-3.5-turbo": 16_384,
}


def parse_args():
    p = argparse.ArgumentParser(
        description="General OpenAI submission helper (auto-chunking, io-dir)"
    )
    p.add_argument("--config", required=True, help="Path to job config (JSON/YAML)")
    p.add_argument("--source", help="Input file to process (payload). If omitted, only messages are sent.")
    p.add_argument("--model", help="Override model")
    p.add_argument("--max-tokens", type=int, help="Override completion cap")
    p.add_argument("--temperature", type=float, help="Override temperature")
    p.add_argument("--job-name", help="Override job name (affects templates)")
    p.add_argument("--io-dir", default=".", help="Prefix for output.path_template and relative --source")
    p.add_argument("--dry-run", action="store_true", help="Compute token budget; do not call the API")
    p.add_argument("--key-file", help="Path to a file containing the OpenAI API key")
    p.add_argument("--key-env", help="Environment variable name that holds the API key (default: OPENAI_API_KEY)")
    p.add_argument("--log-level", default="info",
                   choices=["debug","info","warning","error","critical"],
                   help="Logging verbosity (default: %(default)s)")
    p.add_argument("--output", help="Explicit output file (overrides template; NOT prefixed)")
    p.add_argument("--raw", action="store_true",
                   help="Print raw combined output without pretty JSON formatting")
    return p.parse_args()

def configure_logging(level: str):
    lvl = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(asctime)s %(name)s %(levelname)s: %(message)s",
                        level=lvl)
    logging.getLogger("httpx").setLevel(lvl)
    logging.getLogger("openai").setLevel(lvl)

def make_http_client():
    def log_req(r: httpx.Request):
        size = len(r.content or b"")
        logging.debug(f"→ {r.method} {r.url}  body={size} bytes")
    def log_res(r: httpx.Response):
        length = r.headers.get("content-length") or "unknown"
        logging.debug(f"← {r.status_code} {r.reason_phrase}  body={length} bytes")
    return httpx.Client(event_hooks={"request": [log_req], "response": [log_res]})

def load_config(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        logging.error(f"Config file not found: {path}")
        sys.exit(1)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        if yaml is None:
            logging.error("pyyaml is not installed; cannot load YAML config.")
            sys.exit(1)
        cfg = yaml.safe_load(text)
    else:
        cfg = json.loads(text)
    if not isinstance(cfg, dict):
        logging.error("Config root must be an object/dict.")
        sys.exit(1)
    if "source" in cfg:
        raise SystemExit("Config must not contain 'source'. Provide --source at runtime.")
    if "chunks" in cfg:
        raise SystemExit("Config must not contain 'chunks'. Auto-chunking is internal.")
    if "source_format" in cfg and cfg["source_format"] not in ("json","text","lines"):
        raise SystemExit("source_format must be one of: json, text, lines")
    if "api_key" in cfg:
        raise SystemExit("Config must not contain 'api_key'. Use --key-file or an environment variable instead.")
    outfmt = ((cfg.get("output") or {}).get("format") or "text").lower()
    if outfmt not in ("json","text"):
        raise SystemExit("output.format must be 'json' or 'text'")
    return cfg

def override_config(cfg: Dict[str, Any], args):
    if args.model: cfg["model"] = args.model
    if args.max_tokens is not None: cfg["max_tokens"] = args.max_tokens
    if args.temperature is not None: cfg["temperature"] = args.temperature
    if args.job_name: cfg["job_name"] = args.job_name
    cfg["dry_run"] = bool(args.dry_run)
    if args.output: cfg["output"] = {"path": args.output}  # explicit wins
    if args.raw: cfg["raw"] = True
    cfg["_io_dir"] = args.io_dir
    cfg["_source_path"] = args.source
    return cfg

def get_encoding_for_model(model: str):
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        return tiktoken.get_encoding("cl100k_base")

def count_tokens_for_model(model: str, *texts) -> int:
    enc = get_encoding_for_model(model)
    total = 0
    for t in texts:
        if not t: continue
        total += len(enc.encode(t))
    return total

def desired_response_tokens(cfg: Dict[str, Any], input_tokens: int) -> int:
    override = cfg.get("max_tokens")
    if override is not None:
        return max(1, int(override))
    base = max(1, 2 * input_tokens)
    model = cfg.get("model", "")
    limit = MODEL_COMPLETION_LIMIT.get(model)
    if limit:
        return min(base, int(limit))
    return base


def compute_context_limit(cfg: Dict[str, Any]) -> int:
    ctx_map = dict(MODEL_CONTEXT)
    ctx_map.update(cfg.get("context_window", {}))
    return int(ctx_map.get(cfg.get("model",""), 0))

def strip_markdown_fences(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)

def split_into_chunks(seq: List[Any], n: int) -> List[List[Any]]:
    if n <= 1:
        return [seq]
    size = (len(seq) + n - 1) // n
    return [seq[i:i+size] for i in range(0, len(seq), size)]

def load_from_spec(cfg: Dict[str, Any], spec: Dict[str, Any]) -> str:
    tp = spec.get("type")
    header = spec.get("header", "")
    if tp == "literal":
        return f"{header}{spec.get('text','')}"
    if tp == "file":
        path = Path(spec["path"])
        if not path.is_absolute():
            cfg_path = cfg.get("_config_path")
            if cfg_path:
                path = Path(cfg_path).resolve().parent / path
        if not path.is_file():
            logging.error(f"File not found: {path}")
            sys.exit(1)
        return f"{header}{path.read_text(encoding='utf-8')}"
    logging.error(f"Unsupported 'from' type: {tp}")
    sys.exit(1)

def build_messages(cfg: Dict[str, Any]) -> List[Dict[str, str]]:
    msgs: List[Dict[str, str]] = []
    for m in cfg.get("messages", []):
        role = m.get("role")
        frm = m.get("from", {})
        content = load_from_spec(cfg, frm)
        msgs.append({"role": role, "content": content})
    return msgs

def load_source(cfg: Dict[str, Any]) -> Optional[List[Any]]:
    src_path = cfg.get("_source_path")
    if not src_path:
        return None
    io_dir = Path(cfg.get("_io_dir") or ".")
    p = Path(src_path)
    if not p.is_absolute():
        p = io_dir / p
    resolved = p.resolve()
    cfg["_resolved_source_path"] = str(resolved)
    p = resolved
    if not p.is_file():
        logging.error(f"source file not found: {p}")
        sys.exit(1)
    fmt = cfg.get("source_format", "json")
    text = p.read_text(encoding="utf-8")
    if fmt == "json":
        try:
            arr = json.loads(text)
        except Exception as e:
            logging.error(f"Failed to parse JSON array from --source: {e}")
            sys.exit(1)
        if not isinstance(arr, list):
            logging.error("--source must contain a JSON array when source_format=json")
            sys.exit(1)
        return arr
    elif fmt == "lines":
        return [ln for ln in text.splitlines()]
    elif fmt == "text":
        parts = [pt for pt in text.split("\n\n") if pt.strip()]
        return parts if parts else [text]
    else:
        logging.error(f"Unsupported source_format: {fmt}")
        sys.exit(1)

def derive_output_settings(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out_cfg = cfg.get("output") or {}
    fmt = (out_cfg.get("format") or "text").lower()
    derived = {}
    if fmt == "json":
        derived["parse_each_chunk_as_json"] = True
        derived["aggregate_mode"] = "json_array_concat"
        derived["response_format"] = None   # ← was {"type": "json_object"}
        derived["default_ext"] = "json"
    else:  # text
        derived["parse_each_chunk_as_json"] = False
        derived["aggregate_mode"] = "text_concat"
        derived["response_format"] = None
        derived["default_ext"] = "txt"
    derived["path_template"] = out_cfg.get("path_template") or "{job}-{model}-{srcstem}-{ts}-{pid}-{uuid}." + derived["default_ext"]
    return derived

def estimate_need_for_chunks(cfg: Dict[str, Any],
                             base_messages: List[Dict[str, str]],
                             chunk_data: List[Any],
                             try_chunks: int,
                             ctx_limit: int,
                             byte_limit: int) -> tuple[int, list[int], list[int]]:
    model = cfg.get("model","")
    base_in = sum(count_tokens_for_model(model, m["content"]) for m in base_messages)
    base_bytes = sum(len(m["content"].encode("utf-8")) for m in base_messages)
    pcm = cfg.get("per_chunk_message") or {}
    hdr = pcm.get("header",""); ftr = pcm.get("footer","")
    worst = 0
    per_chunk_tokens: list[int] = []
    per_chunk_bytes: list[int] = []
    for bucket in split_into_chunks(chunk_data, try_chunks):
        if isinstance(bucket, list) and bucket and isinstance(bucket[0], (dict, list)):
            body = json.dumps(bucket)
        else:
            body = "\n".join(map(str, bucket))
        payload = hdr + body + ftr
        in_tokens = base_in + count_tokens_for_model(model, payload)
        out_tokens = desired_response_tokens(cfg, in_tokens)
        need = in_tokens + out_tokens
        worst = max(worst, need)
        per_chunk_tokens.append(in_tokens)
        per_chunk_bytes.append(base_bytes + len(payload.encode('utf-8')))
    return worst, per_chunk_tokens, per_chunk_bytes


def choose_auto_chunks(cfg: Dict[str, Any],
                       base_messages: List[Dict[str, str]],
                       chunk_data: List[Any],
                       ctx_limit: int,
                       byte_limit: int) -> tuple[int, list[int], list[int]]:
    MIN_C = 1
    MAX_C = 64
    latest_tokens: list[int] = []
    latest_bytes: list[int] = []
    for c in range(MIN_C, MAX_C + 1):
        worst, token_breakdown, byte_breakdown = estimate_need_for_chunks(
            cfg, base_messages, chunk_data, c, ctx_limit, byte_limit
        )
        latest_tokens = token_breakdown
        latest_bytes = byte_breakdown
        if worst <= ctx_limit and all(b <= byte_limit for b in byte_breakdown):
            return c, token_breakdown, byte_breakdown
    return MAX_C + 1, latest_tokens, latest_bytes







def format_output_path(cfg: Dict[str, Any], derived: Dict[str, Any]) -> str:
    out = cfg.get("output") or {}
    if isinstance(out, dict) and out.get("path"):
        return out["path"]  # explicit path wins; do not prefix with io-dir
    tpl = derived["path_template"]
    job = cfg.get("job_name") or "job"
    model = cfg.get("model","model")
    src_path = cfg.get("_source_path") or ""
    srcbase = Path(src_path).name if src_path else ""
    srcstem = Path(src_path).stem if src_path else ""
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    pid = os.getpid()
    uid = str(uuid.uuid4())[:8]
    rel = tpl.format(job=job, model=model, srcbase=srcbase, srcstem=srcstem,
                     ts=ts, pid=pid, uuid=uid)
    rel_path = Path(rel)
    if rel_path.is_absolute():
        return str(rel_path)

    src_parent = None
    resolved_src = cfg.get("_resolved_source_path")
    if resolved_src:
        src_parent = Path(resolved_src).parent

    base_dir = src_parent or Path(cfg.get("_io_dir") or ".")
    return str((base_dir / rel_path).resolve())

def call_openai(client: OpenAI, model: str, messages: List[Dict[str,str]],
                temperature: float, max_tokens: int,
                response_format: Optional[Dict[str,Any]]):
    kwargs = dict(model=model, messages=messages,
                  temperature=temperature, max_tokens=max_tokens)
    if response_format:
        kwargs["response_format"] = response_format
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0]
    return choice.message.content



def extract_error_message(exc: BadRequestError) -> str:
    detail = getattr(exc, "message", "") or str(exc)
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            data = response.json()
        except Exception:
            data = None
        if isinstance(data, dict):
            detail = data.get("error", {}).get("message", detail)
    return detail



def request_with_handling(client: OpenAI, model: str, messages: List[Dict[str,str]],
                          temperature: float, max_tokens: int,
                          response_format: Optional[Dict[str,Any]],
                          description: str) -> str:
    try:
        return call_openai(client, model, messages, temperature, max_tokens, response_format)
    except BadRequestError as exc:
        detail = extract_error_message(exc)
        logging.error(f"OpenAI API error during {description}: {detail} (requested max_tokens={max_tokens})")
        sys.exit(1)



def repair_json_string(raw: str) -> str:
    closers = {',', '}', ']', ':', '\n', '\r', ' '}
    out = []
    in_str = False
    escape = False
    for i, ch in enumerate(raw):
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == '\\':
            out.append(ch)
            escape = True
            continue
        if ch == '"':
            if in_str:
                next_char = raw[i + 1] if i + 1 < len(raw) else ''
                if next_char and next_char not in closers:
                    out.append('\"')
                    continue
                in_str = False
            else:
                in_str = True
            out.append(ch)
            continue
        if ch == '\n' and in_str:
            out.append('\n')
            continue
        out.append(ch)
    return ''.join(out)


def aggregate_piece(raw_text: str, parse_json: bool) -> Any:
    cleaned = strip_markdown_fences(raw_text)
    if parse_json:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            repaired = repair_json_string(cleaned)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as e:
                logging.error("Failed to parse JSON from model response:")
                logging.error(cleaned)
                logging.error("After repair attempt:")
                logging.error(repaired)
                logging.error(f"JSONDecodeError: {e}")
                sys.exit(1)
    return cleaned


def combine_results(parts: List[Any], mode: str, pretty: bool) -> str:
    if mode == "json_array_concat":
        combined: List[Any] = []
        for p in parts:
            if isinstance(p, list):
                combined.extend(p)
            elif isinstance(p, dict):
                combined.append(p)  # ← tolerate object-by-chunk
            else:
                raise SystemExit(
                    "json_array_concat requires each response chunk to be a "
                    "JSON array or object; got: " + type(p).__name__
                )
        return json.dumps(combined, indent=(2 if pretty else None))
    else:  # text_concat
        text_parts = [(p if isinstance(p,str) else json.dumps(p)) for p in parts]
        return "\n\n".join(text_parts)

def resolve_api_key(args) -> str:
    # 1) --key-file
    if args.key_file:
        try:
            key = Path(args.key_file).read_text(encoding="utf-8").strip()
        except Exception as e:
            raise SystemExit(f"Failed to read --key-file: {e}")
        if not key:
            raise SystemExit("--key-file is empty")
        return key

    # 2) --key-env (custom env var name)
    if args.key_env:
        key = os.getenv(args.key_env, "").strip()
        if key:
            return key

    # 3) default OPENAI_API_KEY
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if key:
        return key

    raise SystemExit(
        "Missing API key. Provide one via:\n"
        "  --key-file /path/to/key.txt\n"
        "  or set a variable and use --key-env NAME\n"
        "  or export OPENAI_API_KEY in your environment."
    )

def main():
    args = parse_args()
    configure_logging(args.log_level)

    cfg_path = Path(args.config)
    cfg = load_config(cfg_path)
    cfg["_config_path"] = str(cfg_path)
    cfg = override_config(cfg, args)

    api_key = resolve_api_key(args)
    if not api_key:
        logging.error("Missing API key. Set OPENAI_API_KEY or provide api_key in config.")
        sys.exit(1)

    model = cfg.get("model","gpt-4o-mini")
    temperature = float(cfg.get("temperature", 0))

    derived = derive_output_settings(cfg)
    response_format = derived["response_format"]
    parse_json = derived["parse_each_chunk_as_json"]
    aggregate_mode = derived["aggregate_mode"]

    base_messages = build_messages(cfg)

    print("Base message usage:")
    base_tokens_total = 0
    base_bytes_total = 0
    for idx, msg in enumerate(base_messages, start=1):
        content = msg.get("content", "")
        role = msg.get("role", "user")
        tok = count_tokens_for_model(model, content)
        byt = len(content.encode("utf-8"))
        base_tokens_total += tok
        base_bytes_total += byt
        print(f"  base {idx:2d} ({role}): tokens={tok}, bytes={byt}")
    print(f"  total base: tokens={base_tokens_total}, bytes={base_bytes_total}")

    source_data = load_source(cfg)

    ctx_limit = compute_context_limit(cfg)
    byte_limit = 65_536

    tokens_per_chunk: list[int] = []
    bytes_per_chunk: list[int] = []

    if source_data:
        chosen, tokens_per_chunk, bytes_per_chunk = choose_auto_chunks(
            cfg, base_messages, source_data, ctx_limit, byte_limit
        )
        if chosen == 0 or chosen > 64:
            logging.error("Input too large even at max_chunks. Reduce input or increase context.")
            sys.exit(1)
        logging.info(f"Auto-selected chunks: {chosen}")
    else:
        chosen = 1
        base_tokens = sum(count_tokens_for_model(model, m["content"]) for m in base_messages)
        base_bytes = sum(len(m["content"].encode("utf-8")) for m in base_messages)
        tokens_per_chunk = [base_tokens]
        bytes_per_chunk = [base_bytes]
        logging.info("No source provided; sending only base messages.")

    response_tokens = [desired_response_tokens(cfg, tok) for tok in tokens_per_chunk]

    chunk_batches: List[Any] = []
    chunk_lengths: List[int] = []
    if source_data:
        chunk_batches = list(split_into_chunks(source_data, chosen))
        chunk_lengths = [len(chunk) if isinstance(chunk, (list, tuple)) else 1 for chunk in chunk_batches]
    else:
        chunk_lengths = []

    def print_budget(chosen_chunks: int):
        if not tokens_per_chunk or not response_tokens:
            return
        if chosen_chunks <= 1:
            base_in = tokens_per_chunk[0]
            max_out = response_tokens[0]
            need = base_in + max_out
            row_info = f", rows={chunk_lengths[0]}" if chunk_lengths else ""
            print(
                f"FULL submission: input={base_in}, bytes={bytes_per_chunk[0]}, max_output={max_out}, "
                f"total_needed={need}, context={ctx_limit}{row_info}"
            )
        else:
            totals = [tok + resp for tok, resp in zip(tokens_per_chunk, response_tokens)]
            worst = max(totals) if totals else 0
            print(f"Chunks={chosen_chunks} worst-case needed={worst}, context={ctx_limit}")
            for idx, (tok, byt, tot) in enumerate(zip(tokens_per_chunk, bytes_per_chunk, totals), start=1):
                max_out = response_tokens[idx-1] if idx-1 < len(response_tokens) else 0
                row_info = f", rows={chunk_lengths[idx-1]}" if chunk_lengths and idx-1 < len(chunk_lengths) else ""
                print(f"  chunk {idx:2d}: tokens={tok:6d}, bytes={byt:6d}, max_output={max_out:6d}, total_needed={tot:6d}{row_info}")

    print_budget(chosen)
    if cfg.get("dry_run"):
        sys.exit(0)

    client = OpenAI(api_key=api_key, http_client=make_http_client())

    outputs: List[Any] = []

    if not source_data:
        messages = list(base_messages)
        chunk_max_tokens = response_tokens[0] if response_tokens else desired_response_tokens(cfg, base_tokens_total)
        raw = request_with_handling(client, model, messages, temperature, chunk_max_tokens, response_format, "full submission")
        outputs.append(aggregate_piece(raw, parse_json))
    elif chosen <= 1:
        messages = list(base_messages)
        pcm = cfg.get("per_chunk_message") or {}
        hdr = pcm.get("header",""); ftr = pcm.get("footer","")
        role = pcm.get("role","user")
        bucket = chunk_batches[0] if chunk_batches else source_data
        if isinstance(bucket, list) and bucket and isinstance(bucket[0], (dict, list)):
            body = json.dumps(bucket)
        else:
            body = "\n".join(map(str, bucket))
        messages.append({"role": role, "content": hdr + body + ftr})
        chunk_max_tokens = response_tokens[0] if response_tokens else desired_response_tokens(cfg, tokens_per_chunk[0] if tokens_per_chunk else base_tokens_total)
        raw = request_with_handling(client, model, messages, temperature, chunk_max_tokens, response_format, "single chunk submission")
        outputs.append(aggregate_piece(raw, parse_json))
    else:
        pcm = cfg.get("per_chunk_message") or {}
        hdr = pcm.get("header",""); ftr = pcm.get("footer","")
        role = pcm.get("role","user")
        for idx, bucket in enumerate(chunk_batches, start=1):
            messages = list(base_messages)
            if isinstance(bucket, list) and bucket and isinstance(bucket[0], (dict, list)):
                body = json.dumps(bucket)
            else:
                body = "\n".join(map(str, bucket))
            messages.append({"role": role, "content": hdr + body + ftr})
            tok = tokens_per_chunk[idx-1] if idx-1 < len(tokens_per_chunk) else '?'
            byt = bytes_per_chunk[idx-1] if idx-1 < len(bytes_per_chunk) else '?'
            rows = len(bucket) if isinstance(bucket, (list, tuple)) else 'n/a'
            if isinstance(tok, int):
                chunk_max_tokens = response_tokens[idx-1] if idx-1 < len(response_tokens) else desired_response_tokens(cfg, tok)
            else:
                chunk_max_tokens = desired_response_tokens(cfg, 0)
            print(f"Submitting chunk {idx}/{len(chunk_batches)}: rows={rows}, tokens={tok}, bytes={byt}, max_tokens={chunk_max_tokens}")
            description = f"chunk {idx}/{len(chunk_batches)}"
            raw = request_with_handling(client, model, messages, temperature, chunk_max_tokens, response_format, description)
            outputs.append(aggregate_piece(raw, parse_json))

    default_ext = derived["default_ext"]
    out_path = format_output_path(cfg, derived)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    combined = combine_results(outputs, aggregate_mode, pretty=not cfg.get("raw", False))
    Path(out_path).write_text(combined, encoding="utf-8")
    print(f"Wrote combined output to {out_path}")

if __name__ == "__main__":
    main()
