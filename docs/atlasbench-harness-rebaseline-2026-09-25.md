# AtlasBench harness diagnostic — 2026-09-25

The V1 90-item corpus was run locally through the revised Ollama subject with a decoder JSON Schema, `think: false`, `num_predict: 256`, `num_ctx: 4096`, temperature 0, and a 60-second request timeout. These were diagnostic runs; they were not written to the durable benchmark store or used for promotion.

| Model | Correct | Parsed incorrect | Invalid response | Length stops |
| --- | ---: | ---: | ---: | ---: |
| `phi4-mini:latest` | 23 | 67 | 0 | 0 |
| `olmo-3:7b-instruct` | 40 | 50 | 0 | 0 |
| `ministral-3:8b` | 90 | 0 | 0 | 0 |

All three used evaluation policy ID `fdd18d44c9081777364a3d65ea1dfef33fc27641e48ea74c258aeab8d189ef86`. Ollama digests were `78fad5d182a7c33065e153a5f8ba210754207ba9d91973f57dffa7f487363753` (Phi), `ea72df8c85d75c6783ab0d00278803c53a634fc9d0fe38d3fd4ab6f35adbdbb2` (OLMo), and `1922accd5827ebe6829e536369195db25eaf664528dc66206d646ea3bb386b71` (Ministral).

The low Phi and OLMo scores persisted with every response parsed. Their earlier low scores therefore cannot be attributed to JSON failure or output truncation on this corpus. The 90-item corpus alone does not establish why their selected answers were wrong. Ministral retained its perfect score. GPU weight residency was not measured.

A separate live `ministral-3:8b` planner request succeeded under the new planner schema with `think: false` and a 1,800-token output budget. This is a smoke check, not a planner acceptance-rate measurement.
