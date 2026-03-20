# trace-analyzer

用于分析 [Langfuse](https://langfuse.com) trace 数据的 Claude Code 技能，可诊断 Agent 故障、识别错误模式并生成可操作的优化建议。

## 功能

- **单条 Trace 深度分析**：给定 Trace ID，重建完整执行链路，定位失败的 observation，检测死循环，并结合你的代码库定位根因到具体文件和行号
- **批量分析**：获取最近 N 小时的所有 trace，计算成功率，归纳主要失败模式，按影响程度排序优化建议
- **代码关联**：读取你的 Agent 框架源码，将 Langfuse 中的抽象观测结果转化为具体的文件级修复方案
- **智能降级**：当 Langfuse 不可达时，自动读取项目日志文件，产出相同结构的分析报告

## 安装

```bash
# 第一步：将此仓库注册为插件 marketplace
/plugin marketplace add UniBody/trace-analyzer

# 第二步：安装技能
/plugin install trace-analyzer
```

安装完成后，可通过 `/trace-analyzer` 命令调用，或在对话中描述需求时自动触发。

## 使用方式

```
# 分析指定 trace
/trace-analyzer f870f36959f0c3872426f541e86831e1

# 批量分析最近 24 小时
/trace-analyzer --hours 24

# 按 agent 名称过滤
/trace-analyzer --hours 48 --name "my-agent"

# 也可以直接用自然语言描述（技能会自动触发）：
"为什么我的 agent 上次运行失败了？"
"分析最近 6 小时的 trace"
"Langfuse 里的 tool_failure 错误是什么原因？"
```

## 前置条件

**Python 依赖**（首次运行时若缺失会提示安装）：
```bash
pip install requests python-dateutil
```

**Langfuse 凭据** — 技能会自动读取项目根目录或父目录中的 `.env` 文件：
```env
LANGFUSE_HOST=http://localhost:3000        # 或 https://cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

> Docker 用户：`http://host.docker.internal:3000` 会自动转换为 `http://localhost:3000`，无需手动修改。

## 输出示例

```
# Batch Trace Analysis — Last 24h

## Overview
| 指标            | 值     |
|---|---|
| 分析 trace 数   | 47     |
| 成功率          | 83%    |
| 平均 token 消耗 | 8,420  |

## 错误分布
| 错误类型            | 数量 |  %  | 可能原因                         |
|---|---|---|---|
| tool_failure        |  6   | 75% | RAG 服务间歇性不可用              |
| configuration_error |  2   | 25% | 测试环境缺少环境变量              |

## 优化建议（按影响排序）
1. **[紧急]** 为 RAG 工具添加熔断机制 — 可修复 75% 的失败
2. **[中]** 在 staging 环境配置 OPENAI_API_KEY — 修复剩余 25%
```

## 工作原理

技能内置 `scripts/fetch_traces.py`，这是一个独立的 Langfuse REST API 客户端，负责：

1. 自动从当前目录或父目录的 `.env` 文件中读取凭据
2. 通过 `/api/public/traces` 和 `/api/public/observations` 接口获取数据
3. 将错误自动分类为 10 种类型（timeout、tool_failure、configuration_error 等）
4. 检测死循环（同一工具在无进展的情况下被连续调用 5 次以上）
5. 返回结构化 JSON，由 Claude 综合分析并生成报告

## 许可证

MIT
