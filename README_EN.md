# trace-analyzer

A Claude Code skill for analyzing [Langfuse](https://langfuse.com) traces to diagnose Agent failures, identify error patterns, and generate actionable optimization recommendations.

## What it does

- **Single trace deep-dive**: Given a trace ID, reconstructs the full execution flow, identifies which observation failed, detects doom loops, and explains the root cause with links to your codebase
- **Batch analysis**: Fetches the last N hours of traces, calculates success rates, surfaces the top failure patterns, and ranks recommendations by impact
- **Code correlation**: Reads your agent framework source to turn generic observations into file-level fixes
- **Smart fallback**: If Langfuse is unreachable, automatically reads your project's log files and produces the same structured report

## Installation

```bash
# Step 1: Add this repo as a plugin marketplace
/plugin marketplace add UniBody/trace-analyzer

# Step 2: Install the skill
/plugin install trace-analyzer
```

After installation, the skill is available as `/trace-analyzer` or triggers automatically when you ask about traces, agent failures, or Langfuse data.

## Usage

```
# Analyze a specific trace
/trace-analyzer f870f36959f0c3872426f541e86831e1

# Batch analysis — last 24 hours
/trace-analyzer --hours 24

# Filter by agent name
/trace-analyzer --hours 48 --name "my-agent"

# Or just describe what you want (skill auto-triggers):
"Why did my agent fail on the last run?"
"Analyze the traces from the past 6 hours"
"What's causing the tool_failure errors in Langfuse?"
```

## Prerequisites

**Python packages** (auto-installed on first run if missing):
```bash
pip install requests python-dateutil
```

**Langfuse credentials** — the skill reads from your project's `.env` automatically:
```env
LANGFUSE_HOST=http://localhost:3000        # or https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

Docker users: `http://host.docker.internal:3000` is automatically converted to `http://localhost:3000`.

## Example output

```
# Batch Trace Analysis — Last 24h

## Overview
| Metric        | Value  |
|---|---|
| Traces analyzed | 47   |
| Success rate  | 83%    |
| Avg tokens    | 8,420  |

## Error Breakdown
| Error Type      | Count | % | Likely Cause                        |
|---|---|---|---|
| tool_failure    | 6     | 75% | RAG service intermittently down     |
| configuration_error | 2 | 25% | Missing env var in staging          |

## Top Recommendations
1. **[Critical]** Add circuit-breaker around RAG tool — fixes 75% of failures
2. **[Medium]** Set OPENAI_API_KEY in staging .env — fixes remaining 25%
```

## How it works

The skill uses `scripts/fetch_traces.py` — a standalone Langfuse REST API client that:

1. Auto-discovers credentials from `.env` in the current or parent directories
2. Fetches traces and observations via `/api/public/traces` and `/api/public/observations`
3. Classifies errors into 10 categories (timeout, tool_failure, configuration_error, etc.)
4. Detects doom loops (same tool called 5+ times without progress)
5. Returns structured JSON for Claude to synthesize into a report

## License

MIT
