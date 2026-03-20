#!/usr/bin/env python3
"""
Langfuse Trace Fetcher & Analyzer
Usage:
  python fetch_traces.py --trace-id <id>              # single trace deep analysis
  python fetch_traces.py --hours 24 --limit 50        # batch analysis
  python fetch_traces.py --hours 24 --name <agent>    # filter by agent name
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

# ── Config ──────────────────────────────────────────────────────────────────

def load_config():
    """Load Langfuse credentials from .env or environment variables."""
    # Try to read .env in current directory or parent dirs
    for path in [".", "..", "../..", "../../.."]:
        env_file = os.path.join(path, ".env")
        if os.path.isfile(env_file):
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key.startswith("LANGFUSE") and not os.environ.get(key):
                            os.environ[key] = val
            break

    host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000").rstrip("/")

    # Auto-convert Docker internal address to localhost for host machine access
    if "host.docker.internal" in host:
        original_host = host
        host = host.replace("host.docker.internal", "localhost")
        print(f"[INFO] Converted Docker internal address: {original_host} → {host}", file=sys.stderr)

    pub  = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sec  = os.environ.get("LANGFUSE_SECRET_KEY", "")
    return host, pub, sec


def check_connection(host, pub, sec):
    """Verify Langfuse connection. Returns (ok, message)."""
    try:
        r = requests.get(f"{host}/api/public/traces?limit=1",
                         auth=(pub, sec), timeout=10)
        if r.status_code == 200:
            return True, "Connected"
        elif r.status_code == 401:
            return False, "Authentication failed — check LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY"
        else:
            return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except requests.exceptions.ConnectionError:
        return False, f"Cannot reach {host} — is the server running?"
    except Exception as e:
        return False, str(e)


# ── Fetch ────────────────────────────────────────────────────────────────────

def get_trace(host, pub, sec, trace_id):
    r = requests.get(f"{host}/api/public/traces/{trace_id}",
                     auth=(pub, sec), timeout=30)
    if r.status_code == 404:
        print(f"[ERROR] Trace '{trace_id}' not found", file=sys.stderr)
        return None
    r.raise_for_status()
    return r.json()


def list_traces(host, pub, sec, from_ts, limit=50, name_filter=None):
    params = {
        "fromTimestamp": from_ts.isoformat(),
        "limit": limit,
        "orderBy": "timestamp.DESC",
    }
    if name_filter:
        params["name"] = name_filter
    r = requests.get(f"{host}/api/public/traces",
                     params=params, auth=(pub, sec), timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def get_observations(host, pub, sec, trace_id):
    # Use smaller limit to avoid 400 errors with large traces
    r = requests.get(f"{host}/api/public/observations",
                     params={"traceId": trace_id, "limit": 100},
                     auth=(pub, sec), timeout=60)
    r.raise_for_status()
    return r.json().get("data", [])


# ── Analysis ─────────────────────────────────────────────────────────────────

ERROR_PATTERNS = {
    "timeout":             ["timeout", "time limit exceeded", "deadline", "took too long", "timed out"],
    "oom_killed":          ["killed", "exit code 137", "out of memory", "oom", "memory error"],
    "configuration_error": ["does not support", "missing key", "api key", "invalid config", "not configured"],
    "tool_failure":        ["tool error", "execution failed", "command not found", "exit code", "subprocess"],
    "rate_limit":          ["rate limit", "quota exceeded", "too many requests", "429"],
    "auth_error":          ["unauthorized", "forbidden", "401", "403", "authentication"],
    "planning_loop":       ["stuck in loop", "doom loop", "repeated attempts", "infinite loop"],
    "context_missing":     ["insufficient context", "missing information", "file not found", "not found"],
    "hallucination":       ["incorrect", "wrong answer", "does not match", "hallucination"],
}


def classify_error(msg: str) -> str:
    msg_l = str(msg).lower()
    for etype, keywords in ERROR_PATTERNS.items():
        if any(kw in msg_l for kw in keywords):
            return etype
    return "unknown"


def parse_duration_ms(start, end) -> float:
    if not (start and end):
        return 0.0
    try:
        from dateutil import parser as dparser
        s = dparser.isoparse(start)
        e = dparser.isoparse(end)
        return (e - s).total_seconds() * 1000
    except Exception:
        return 0.0


def analyze_single_trace(trace, observations):
    """Full deep analysis of one trace."""
    errors = []
    tool_calls = []
    llm_calls = []
    total_tokens = {"input": 0, "output": 0, "total": 0}
    total_duration_ms = 0.0

    for obs in observations:
        dur = parse_duration_ms(obs.get("startTime"), obs.get("endTime"))
        total_duration_ms += dur

        # Token aggregation
        usage = obs.get("usage") or {}
        for k in ("input", "output", "total"):
            total_tokens[k] += usage.get(k, 0)
        if usage:
            llm_calls.append({
                "name":  obs.get("name"),
                "model": obs.get("model"),
                "usage": usage,
                "duration_ms": round(dur),
            })

        # Tool calls
        if obs.get("type") == "TOOL":
            status = obs.get("status", "unknown")
            err_msg = obs.get("statusMessage") if status == "ERROR" else None
            tool_calls.append({
                "name":       obs.get("name"),
                "status":     status,
                "duration_ms": round(dur),
                "error":      err_msg,
            })

        # Error detection
        if obs.get("status") == "ERROR" or obs.get("level") == "ERROR":
            err_msg = obs.get("statusMessage") or str(obs.get("output", ""))[:200]
            errors.append({
                "observation": obs.get("name"),
                "type": obs.get("type"),
                "message": err_msg,
                "classified_as": classify_error(err_msg),
            })

    # Loop detection
    tool_name_counts = Counter(tc["name"] for tc in tool_calls)
    loops = {name: cnt for name, cnt in tool_name_counts.items() if cnt > 5}

    # Determine overall status
    trace_status = "success"
    if errors:
        trace_status = "error"
    elif trace.get("output") and isinstance(trace["output"], dict):
        if trace["output"].get("error"):
            trace_status = "error"
            errors.append({
                "observation": "trace_output",
                "type": "TRACE",
                "message": str(trace["output"]["error"])[:200],
                "classified_as": classify_error(str(trace["output"]["error"])),
            })

    return {
        "id":               trace.get("id"),
        "name":             trace.get("name"),
        "timestamp":        trace.get("timestamp"),
        "status":           trace_status,
        "duration_ms":      round(total_duration_ms),
        "token_usage":      total_tokens,
        "observations_count": len(observations),
        "tool_calls":       tool_calls,
        "tool_call_count":  len(tool_calls),
        "llm_calls":        llm_calls,
        "llm_call_count":   len(llm_calls),
        "errors":           errors,
        "loops_detected":   loops,
        "tags":             trace.get("tags", []),
        "scores":           trace.get("scores", []),
        "input":            trace.get("input"),
        "output":           trace.get("output"),
    }


def batch_summary(analyses):
    """Summarize multiple trace analyses into aggregate stats."""
    total = len(analyses)
    if total == 0:
        return {"total": 0}

    success = sum(1 for a in analyses if a["status"] == "success")
    error_types = Counter()
    tool_usage  = Counter()
    total_tokens = 0
    total_duration = 0

    for a in analyses:
        for err in a.get("errors", []):
            error_types[err["classified_as"]] += 1
        for tc in a.get("tool_calls", []):
            tool_usage[tc["name"]] += 1
        total_tokens   += a["token_usage"].get("total", 0)
        total_duration += a.get("duration_ms", 0)

    return {
        "total":          total,
        "success":        success,
        "failed":         total - success,
        "success_rate":   f"{success / total * 100:.1f}%",
        "avg_duration_s": round(total_duration / total / 1000, 1),
        "avg_tokens":     round(total_tokens / total) if total else 0,
        "error_breakdown": dict(error_types.most_common()),
        "top_tools":      dict(tool_usage.most_common(10)),
    }


# ── Output ───────────────────────────────────────────────────────────────────

def print_single_report(analysis):
    a = analysis
    status_icon = "✅" if a["status"] == "success" else "❌"

    print(f"\n{'='*60}")
    print(f"Trace Deep Analysis")
    print(f"{'='*60}")
    print(f"  ID:          {a['id']}")
    print(f"  Agent:       {a['name']}")
    print(f"  Timestamp:   {a['timestamp']}")
    print(f"  Status:      {status_icon} {a['status'].upper()}")
    print(f"  Duration:    {a['duration_ms']}ms ({a['duration_ms']/1000:.1f}s)")
    print(f"  Tokens:      {a['token_usage']['input']}in / {a['token_usage']['output']}out / {a['token_usage']['total']}total")
    print(f"  Observations:{a['observations_count']}")
    print(f"  Tool Calls:  {a['tool_call_count']}")
    print(f"  LLM Calls:   {a['llm_call_count']}")

    if a["errors"]:
        print(f"\n--- Errors ({len(a['errors'])}) ---")
        for e in a["errors"]:
            print(f"  [{e['classified_as']}] {e['observation']}: {e['message'][:120]}")

    if a["loops_detected"]:
        print(f"\n--- Loop Detection ---")
        for tool, cnt in a["loops_detected"].items():
            print(f"  ⚠️  '{tool}' called {cnt} times — possible loop")

    if a["tool_calls"]:
        print(f"\n--- Tool Calls ---")
        for tc in a["tool_calls"]:
            icon = "✅" if tc["status"] != "ERROR" else "❌"
            print(f"  {icon} {tc['name']} ({tc['duration_ms']}ms)")

    if a["llm_calls"]:
        print(f"\n--- LLM Calls ---")
        for lc in a["llm_calls"]:
            u = lc["usage"]
            print(f"  {lc['name']} [{lc['model']}] — {u.get('total',0)} tokens")


def print_batch_report(summary, analyses):
    print(f"\n{'='*60}")
    print(f"Batch Analysis Report")
    print(f"{'='*60}")
    print(f"  Total traces:   {summary['total']}")
    print(f"  Successful:     {summary['success']} ({summary['success_rate']})")
    print(f"  Failed:         {summary['failed']}")
    print(f"  Avg duration:   {summary['avg_duration_s']}s")
    print(f"  Avg tokens:     {summary['avg_tokens']}")

    if summary["error_breakdown"]:
        print(f"\n--- Error Breakdown ---")
        for etype, cnt in summary["error_breakdown"].items():
            pct = cnt / summary["total"] * 100
            print(f"  {etype:<25} {cnt:>3}x  ({pct:.1f}%)")

    if summary["top_tools"]:
        print(f"\n--- Top Tool Usage ---")
        for tool, cnt in summary["top_tools"].items():
            print(f"  {tool:<30} {cnt:>4}x")

    # Show failed traces detail
    failed = [a for a in analyses if a["status"] != "success"]
    if failed:
        print(f"\n--- Failed Traces ---")
        for a in failed[:10]:
            err_summary = "; ".join(
                f"{e['classified_as']}" for e in a.get("errors", [])
            ) or "unknown"
            print(f"  {a['id'][:20]}  {a['name']}  → {err_summary}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Langfuse Trace Analyzer")
    p.add_argument("--trace-id",  help="Analyze a specific trace ID")
    p.add_argument("--hours",     type=float, default=24, help="Lookback window in hours (default: 24)")
    p.add_argument("--limit",     type=int,   default=50, help="Max traces for batch mode (default: 50)")
    p.add_argument("--name",      help="Filter traces by agent name")
    p.add_argument("--json",      action="store_true", help="Output raw JSON instead of formatted report")
    p.add_argument("--host",      help="Override LANGFUSE_HOST")
    p.add_argument("--pub",       help="Override LANGFUSE_PUBLIC_KEY")
    p.add_argument("--sec",       help="Override LANGFUSE_SECRET_KEY")
    args = p.parse_args()

    host, pub, sec = load_config()
    if args.host: host = args.host
    if args.pub:  pub  = args.pub
    if args.sec:  sec  = args.sec

    # Validate
    if not pub or not sec:
        print("[ERROR] Missing Langfuse credentials.", file=sys.stderr)
        print("Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env or environment.", file=sys.stderr)
        sys.exit(1)

    ok, msg = check_connection(host, pub, sec)
    if not ok:
        print(f"[ERROR] {msg}", file=sys.stderr)
        print("\nTroubleshooting:", file=sys.stderr)
        print(f"  curl -u '$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY' '{host}/api/public/traces?limit=1'", file=sys.stderr)
        sys.exit(1)

    # Single trace mode
    if args.trace_id:
        trace = get_trace(host, pub, sec, args.trace_id)
        if not trace:
            sys.exit(1)
        observations = get_observations(host, pub, sec, args.trace_id)
        analysis = analyze_single_trace(trace, observations)

        if args.json:
            print(json.dumps(analysis, indent=2, ensure_ascii=False, default=str))
        else:
            print_single_report(analysis)
        return

    # Batch mode
    from_ts = datetime.now(timezone.utc) - timedelta(hours=args.hours)
    traces = list_traces(host, pub, sec, from_ts, limit=args.limit, name_filter=args.name)
    if not traces:
        print(f"No traces found in the last {args.hours}h.")
        return

    print(f"Fetched {len(traces)} traces, analyzing...", file=sys.stderr)
    analyses = []
    for t in traces:
        obs = get_observations(host, pub, sec, t["id"])
        analyses.append(analyze_single_trace(t, obs))

    summary = batch_summary(analyses)

    if args.json:
        print(json.dumps({"summary": summary, "traces": analyses},
                         indent=2, ensure_ascii=False, default=str))
    else:
        print_batch_report(summary, analyses)


if __name__ == "__main__":
    main()
