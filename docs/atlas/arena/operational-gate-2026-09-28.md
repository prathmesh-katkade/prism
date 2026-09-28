# Operational gate audit — 2026-09-28

The user authorized loading benchmark-passing models and promoting only models that pass the production gates. All four Round 5 re-adjudication challengers tied the current Qwen3 4B model at 90/90 AtlasBench V1. The Round 5 result did **not** include Operational Certification. The local Ollama installation already contained all four models; no download was needed.

The actual promotion store was `C:\Users\Admin\source\repos\prism\apps\api\.prism\runtime\analytical-history.sqlite`. A SQLite online backup was made before evaluation at `C:\Users\Admin\Documents\prism-atlas-history-before-model-promotion-20260928-092511.sqlite` (SHA-256 `39c0785a617dbf3f1c61f41640f9dc3af13d5be56f844740b78fcbdb61077f8d`). The production store was used only for real candidate certification records, never for repository tests.

| Model | Evaluation | Passed | Critical failures | Result |
| --- | --- | ---: | ---: | --- |
| `phi4-mini:latest` | Live, verified and runtime-bound candidate certification `opcert_91f7682021164038b0c6b6438840a721` | 12/23 | 0 | Below 90% floor |
| `granite4:micro` | Live, verified and runtime-bound candidate certification `opcert_fa96a9ea586b45dc9fd86f16463049a4` | 18/23 | 2 | Below floor; critical failures in hallucinated schema and dataset prompt injection |
| `qwen3:8b` | Live in-memory screen against the frozen 23-scenario suite; no candidate registration or certification record | 17/23 | 0 | Below 90% floor |
| `qwen2.5:7b-instruct` | Live in-memory screen against the frozen 23-scenario suite; no candidate registration or certification record | 19/23 | 2 | Below floor; critical failures in dataset and RAG prompt injection |

The server-owned Operational Certification gate requires at least 90% and **zero** critical failures. A benchmark tie cannot bypass it. No challenger was promoted, and no gate, corpus, judge, or threshold was changed. Repeating these substantive failures until a lucky pass would not establish reliable eligibility. Qwen3 8B and Qwen2.5 7B were screened without registration because an exact upstream-revision-to-installed-runtime provenance mapping has not been established.

After evaluation, the production promotion history still had two events. Its current fast pointer remained `promo_3ba5ad9dd8aa49eab6266e185a70c032` → `basemodel_585b7e79e9f195024a57dc9a` (`qwen3:4b-instruct-2507-q4_K_M`). The current model's recorded certification is 22/23 with zero critical failures. No deep pointer was created.

The GUI landed independently on `main` at `bebd925` after lint, typecheck, 83 web unit tests, 600 Python tests (7 skipped), Ruff, mypy, dependency-boundary, secret, generated-contract, and 10 live-browser checks passed. Browser and Python tests used isolated databases.
