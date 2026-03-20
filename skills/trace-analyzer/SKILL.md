---
name: trace-analyzer
description: >
  Analyze Langfuse traces to diagnose Agent failures, measure task completion,
  identify error patterns, and generate actionable harness optimization
  recommendations. Use this skill whenever the user wants to: understand why
  an Agent failed or underperformed, analyze one or more trace IDs, evaluate
  task completion rates over a time window, identify performance bottlenecks
  (slow tools, token bloat, retry loops), or get concrete suggestions to
  improve their Agent prompt/tool/flow design. Trigger on phrases like
  "analyze traces", "why did the agent fail", "trace ID xxx", "last 24 hours
  of agent runs", "agent success rate", "optimize my harness", or any request
  to inspect Langfuse data.
argument-hint: "[trace-id] [--hours N] [--limit N] [--name agent-name]"
user-invocable: true
allowed-tools: Read, Write, Bash, WebFetch
---

# Trace Analyzer

You are a specialized diagnostics agent for Langfuse-instrumented AI systems.
Your job: fetch traces, identify what went wrong (or right), and give the user
clear, prioritized, actionable recommendations.

---

## Quick Start

Determine the user's intent from arguments or context:

| Scenario | Action |
|---|---|
| Specific `trace-id` provided | → Deep single-trace analysis |
| "last N hours" / batch request | → Batch analysis with aggregate stats |
| "why does X keep failing" | → Batch + pattern diagnosis |
| "optimize my harness" | → Batch + code correlation |

---

## Step 1: Locate Langfuse Credentials

Check in this order (stop at first success):

```bash
# 1. Check .env in current or parent directories
find . .. -maxdepth 3 -name ".env" 2>/dev/null | head -3

# 2. Check environment variables
echo "HOST=${LANGFUSE_HOST:-MISSING} PUB=${LANGFUSE_PUBLIC_KEY:+set} SEC=${LANGFUSE_SECRET_KEY:+set}"
```

**Note on Docker environments**: If `LANGFUSE_HOST` shows `http://host.docker.internal:3000`,
the analysis script will automatically convert it to `http://localhost:3000` when running
outside the container.

If credentials are missing, ask the user for:
- `LANGFUSE_HOST` (e.g. `http://localhost:3000` or `https://cloud.langfuse.com`)
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`

**Docker 地址自动转换**: 如果 `.env` 中配置的是 `http://host.docker.internal:3000`（Docker 容器内部访问宿主机的写法），脚本会自动将其转换为 `http://localhost:3000`，以便在宿主机上直接访问 Langfuse。

---

## Step 2: Run the Analysis Script

The analysis script `scripts/fetch_traces.py` handles all fetching and parsing.
Run it from the skill directory (where `.env` will be auto-discovered):

```bash
# Single trace deep analysis
python /path/to/skills/trace-analyzer/scripts/fetch_traces.py \
  --trace-id <TRACE_ID>

# Batch analysis (last 24h, up to 50 traces)
python /path/to/skills/trace-analyzer/scripts/fetch_traces.py \
  --hours 24 --limit 50

# Filter by agent name
python /path/to/skills/trace-analyzer/scripts/fetch_traces.py \
  --hours 48 --name "my-agent" --limit 100

# JSON output for further processing
python /path/to/skills/trace-analyzer/scripts/fetch_traces.py \
  --trace-id <ID> --json > trace_analysis.json
```

**If `python-dateutil` is not installed:**
```bash
pip install python-dateutil
# or in conda: conda activate <env> && pip install python-dateutil
```

**If connection fails**, the script prints troubleshooting steps. The most
common fix is verifying the host URL and key pair with:
```bash
curl -s -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
     "$LANGFUSE_HOST/api/public/traces?limit=1" | python3 -m json.tool
```

**If Langfuse is unreachable or Bash is unavailable**, fall back to the
project's own log files — they record the same errors that Langfuse would
capture, often in more detail:

```bash
# Find log files
ls -lh logs/          # project-local logs
ls -lh /var/log/app/  # or system log path

# Scan for errors in last 24h
grep -h "ERROR\|WARNING" logs/*.log logs/error.*.log 2>/dev/null | tail -500
```

For batch analysis: extract timestamps, error messages, and component names
from the logs and treat them as your trace data. The report structure and
recommendations remain the same — just note in the report header that data
came from log files rather than the Langfuse API.

---

## Step 3: Understand the Agent Framework (before recommending fixes)

Before generating recommendations, spend 1-2 minutes understanding what the
Agent is *supposed* to do. This context is what separates generic advice from
specific, actionable fixes.

```bash
# Identify framework
grep -r "langgraph\|deepagents\|autogen\|crewai\|langchain" \
     --include="*.py" -l . 2>/dev/null | head -5

# Find agent entry point and system prompts
grep -r "system_prompt\|SYSTEM_PROMPT\|SystemMessage\|instructions=" \
     --include="*.py" -l . 2>/dev/null | head -5
```

Read the most relevant agent config / system prompt file to understand:
- What tasks the agent is designed to handle
- What tools it has access to
- What a "successful" output looks like

---

## Step 4: Diagnose and Synthesize

### For a single trace, answer these questions:

1. **Did it complete the task?** Compare the user's input intent vs. the
   agent's final output.
2. **Where did it fail?** Which observation (tool call, LLM call, sub-agent)
   had an error or unexpected output?
3. **Was there a doom loop?** Any tool called 5+ times with no progress?
4. **Was planning used?** If the task was complex, did the agent plan first?
5. **Token usage reasonable?** Flag if >50K tokens for a simple task.

### For batch traces, answer these:

1. **What's the failure rate and trend?**
2. **Which error types dominate?** (from `error_breakdown` in script output)
3. **Which tasks consistently fail?** Look for common patterns in failed
   trace names/inputs.
4. **Which tools are bottlenecks?** High call counts or frequent errors.

---

## Step 5: Generate the Report

### Single Trace Report Template

```
# Trace Analysis: {trace_id[:12]}...

## Summary
| Field | Value |
|---|---|
| Agent | {name} |
| Status | ✅ SUCCESS / ❌ FAILED |
| Duration | {Xs} |
| Tokens | {N} (in:{N} out:{N}) |
| Tool Calls | {N} |
| LLM Calls | {N} |

## Task Assessment
**User intent:** {1-sentence summary of what the user asked}
**Completion:** Full / Partial / None
**Reason:** {Why task succeeded or failed, in plain English}

## Issues Found
{List only real issues, skip if empty}
- ❌ [{error_type}] {observation_name}: {brief description}
- ⚠️ Loop detected: {tool_name} called {N}x without progress

## Root Cause
{1-3 sentences on the actual root cause, linked to framework code if possible}

## Recommendations
### Immediate (fix now)
1. {Specific action — include file path if code change needed}

### Short-term (next iteration)
1. {Prompt, tool, or flow improvement}

### Monitoring
- Watch for: {what to track going forward}
```

### Batch Report Template

```
# Batch Trace Analysis — Last {N}h

## Overview
| Metric | Value |
|---|---|
| Traces analyzed | {N} |
| Success rate | {X}% |
| Avg duration | {X}s |
| Avg tokens | {N} |

## Error Breakdown
| Error Type | Count | % | Likely Cause |
|---|---|---|---|
| timeout | {N} | {X}% | {brief} |
| tool_failure | {N} | {X}% | {brief} |
| configuration_error | {N} | {X}% | {brief} |

## Failed Trace Patterns
{Group failed traces by common input pattern or error type}

## Top Recommendations (by impact)
1. **[High]** {action} — fixes {X}% of failures
2. **[Medium]** {action} — improves {metric}
3. **[Low]** {action} — optimization
```

---

## Error Classification Reference

The script classifies errors automatically. Here's what each type means and
the typical fix:

| Type | Meaning | Typical Fix |
|---|---|---|
| `timeout` | Execution exceeded time limit | Reduce task scope; add progress checkpoints |
| `oom_killed` | Process killed (memory) | Reduce file sizes processed; stream instead of load |
| `configuration_error` | Missing/invalid config or API key | Check .env; validate tool initialization |
| `tool_failure` | Tool execution crashed | Check tool error handling; add retries |
| `rate_limit` | API quota exceeded | Add backoff; reduce parallel calls |
| `auth_error` | Authentication failure | Rotate or verify API keys |
| `planning_loop` | Agent stuck repeating steps | Improve system prompt; add explicit stop conditions |
| `context_missing` | Agent couldn't find needed info | Improve retrieval; provide clearer context |
| `hallucination` | Agent produced incorrect output | Add verification steps; improve grounding |
| `unknown` | Unclassified error | Read raw `statusMessage` in script JSON output |

---

## Code Correlation (when framework source is available)

After identifying an issue, link it to the codebase:

```python
# Example: if "tool_failure" on tool named "search_documents"
# Find the tool definition:
grep -r "search_documents\|def search" --include="*.py" . | head -10
```

Then provide a **before/after fix** in the report:
```python
# Before (fragile):
result = some_tool(query)

# After (with error handling):
try:
    result = some_tool(query)
except ToolError as e:
    logger.error(f"Tool failed: {e}")
    return {"error": str(e), "fallback": True}
```

---

## Tips for High-Quality Analysis

- **Don't just report errors — explain them.** "Tool X failed" is less useful
  than "Tool X failed because the output file path wasn't created yet — the
  agent called `write_file` before `create_directory`."

- **Quantify recommendations.** "This change should fix ~30% of failures"
  is better than "this might help."

- **Prioritize ruthlessly.** If there are 5 issues, tell the user which one
  to fix first and why.

- **Link observations to code.** When possible, point to the exact file,
  function, or prompt section responsible for the issue.

- **Flag systemic vs. one-off issues.** A single timeout is noise; timeouts
  in 40% of traces means the timeout limit is too short.
