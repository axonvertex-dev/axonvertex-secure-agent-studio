# Checkpoint 2A — Long-Context Positional Retrieval

## Result

**20/20 cases passed.**

| Profile | Prompt tokens | Passed | Mean latency | Min | Max | Cached |
|---|---:|---:|---:|---:|---:|---:|
| 32k | 28152 | 5/5 | 34.1s | 29.3s | 36.1s | 0 |
| 64k | 60911 | 5/5 | 126.7s | 94.5s | 223.5s | 0 |
| 96k | 93717 | 5/5 | 253.2s | 181.4s | 438.1s | 0 |
| 128k | 126476 | 5/5 | 318.1s | 316.3s | 318.7s | 0 |

## Protocol

- SGLang radix cache flushed before every case.
- Evidence positions: 5%, 25%, 50%, 75%, 95%.
- Output reserve: 4,096 tokens.
- Construction safety margin: 512 tokens.
- Prompt construction tolerance: ±128 tokens.
- Server-side `/v1/messages/count_tokens` calibrated against actual `usage.prompt_tokens` with zero delta.

## Supported conclusion

Gemma 4 12B QAT on Node A successfully recovered a single authoritative fact across every tested evidence position at approximately 28K, 61K, 94K, and 126K prompt-token scales under controlled cold-cache conditions.

## Not established by this benchmark

- Distributed-evidence reasoning.
- Cross-file or repository-level reasoning.
- Security diagnosis quality.
- Optimal context budget selection.
- Recursive retrieval/RLM performance.

## Observed performance anomaly

The 64K and 96K 75%-position runs exhibited unusually high latency. Retrieval remained correct. The 128K cold-cache runs were comparatively uniform across positions, so no position-dependent compute conclusion is drawn from the anomaly.
