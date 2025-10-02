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
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # optional for YAML configs
except Exception:
    yaml = None

import httpx
import tiktoken
from openai import OpenAI

MODEL_CONTEXT = {
    "gpt-4.1":        1_000_000,
    "gpt-4.1-mini":   1_000_000,
    "gpt-4.1-nano":   1_000_000,
    "gpt-4o":           128_000,
    "gpt-4o-mini":      128_000,
    "gpt-4":              8_192,
    "gpt-4-32k":        32_768,
    "gpt-3.5-turbo":     16_384,
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

def load_from_spec(spec: Dict[str, Any]) -> str:
    tp = spec.get("type")
    header = spec.get("header", "")
    if tp == "literal":
        return f"{header}{spec.get('text','')}"
    if tp == "file":
        path = Path(spec["path"])
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
        content = load_from_spec(frm)
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
                             try_chunks: int) -> int:
    model = cfg.get("model","")
    max_out = int(cfg.get("max_tokens", 0))
    base_in = sum(count_tokens_for_model(model, m["content"]) for m in base_messages)
    pcm = cfg.get("per_chunk_message") or {}
    hdr = pcm.get("header",""); ftr = pcm.get("footer","")
    worst = 0
    for bucket in split_into_chunks(chunk_data, try_chunks):
        if isinstance(bucket, list) and bucket and isinstance(bucket[0], (dict, list)):
            body = json.dumps(bucket)
        else:
            body = "\n".join(map(str, bucket))
        in_tokens = base_in + count_tokens_for_model(model, hdr + body + ftr)
        need = in_tokens + max_out
        worst = max(worst, need)
    return worst

def choose_auto_chunks(cfg: Dict[str, Any],
                       base_messages: List[Dict[str, str]],
                       chunk_data: List[Any],
                       ctx_limit: int) -> int:
    MIN_C = 1
    MAX_C = 64
    for c in range(MIN_C, MAX_C + 1):
        worst = estimate_need_for_chunks(cfg, base_messages, chunk_data, c)
        if worst <= ctx_limit:
            return c
    return MAX_C + 1

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
    io_dir = Path(cfg.get("_io_dir") or ".")
    return str(io_dir / rel)

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

def aggregate_piece(raw_text: str, parse_json: bool) -> Any:
    if parse_json:
        try:
            return json.loads(strip_markdown_fences(raw_text))
        except Exception as e:
            logging.error("Failed to parse JSON from model response:")
            logging.error(raw_text)
            logging.error(f"Error: {e}")
            sys.exit(1)
    else:
        return strip_markdown_fences(raw_text)

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
    max_tokens = int(cfg.get("max_tokens", 16000))

    derived = derive_output_settings(cfg)
    response_format = derived["response_format"]
    parse_json = derived["parse_each_chunk_as_json"]
    aggregate_mode = derived["aggregate_mode"]

    base_messages = build_messages(cfg)
    source_data = load_source(cfg)

    ctx_limit = compute_context_limit(cfg)

    if source_data:
        chosen = choose_auto_chunks(cfg, base_messages, source_data, ctx_limit)
        if chosen == 0 or chosen > 64:
            logging.error("Input too large even at max_chunks. Reduce input or increase context.")
            sys.exit(1)
        logging.info(f"Auto-selected chunks: {chosen}")
    else:
        chosen = 1
        logging.info("No source provided; sending only base messages.")

    def print_budget(chosen_chunks: int):
        if not source_data or chosen_chunks <= 1:
            base_in = sum(count_tokens_for_model(model, m["content"]) for m in base_messages)
            need = base_in + max_tokens
            print(f"FULL submission: input={base_in}, max_output={max_tokens}, total_needed={need}, context={ctx_limit}")
        else:
            worst = estimate_need_for_chunks(cfg, base_messages, source_data, chosen_chunks)
            print(f"Chunks={chosen_chunks} worst-case needed={worst}, context={ctx_limit}")

    print_budget(chosen)
    if cfg.get("dry_run"):
        sys.exit(0)

    client = OpenAI(api_key=api_key, http_client=make_http_client())

    outputs: List[Any] = []

    if not source_data or chosen <= 1:
        messages = list(base_messages)
        if source_data:
            pcm = cfg.get("per_chunk_message") or {}
            hdr = pcm.get("header",""); ftr = pcm.get("footer","")
            role = pcm.get("role","user")
            body = json.dumps(source_data) if isinstance(source_data, list) else str(source_data)
            messages.append({"role": role, "content": hdr + body + ftr})
        raw = call_openai(client, model, messages, temperature, max_tokens, response_format)
        outputs.append(aggregate_piece(raw, parse_json))
    else:
        pcm = cfg.get("per_chunk_message") or {}
        hdr = pcm.get("header",""); ftr = pcm.get("footer","")
        role = pcm.get("role","user")
        for bucket in split_into_chunks(source_data, chosen):
            messages = list(base_messages)
            if isinstance(bucket, list) and bucket and isinstance(bucket[0], (dict, list)):
                body = json.dumps(bucket)
            else:
                body = "\n".join(map(str, bucket))
            messages.append({"role": role, "content": hdr + body + ftr})
            raw = call_openai(client, model, messages, temperature, max_tokens, response_format)
            outputs.append(aggregate_piece(raw, parse_json))

    default_ext = derived["default_ext"]
    out_path = format_output_path(cfg, derived)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    combined = combine_results(outputs, aggregate_mode, pretty=not cfg.get("raw", False))
    Path(out_path).write_text(combined, encoding="utf-8")
    print(f"Wrote combined output to {out_path}")

if __name__ == "__main__":
    main()
