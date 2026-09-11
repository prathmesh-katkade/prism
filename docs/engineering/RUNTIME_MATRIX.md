# Runtime matrix

| Runtime | Local verification | CI / deployment target | Reason |
|---|---:|---:|---|
| Python | 3.9+ | 3.11 | The current checkout has a working 3.9 virtual environment; CI retains 3.11, matching the legacy Render runtime. |
| Node.js | 24.x | 24.x | Pinned workspace tooling baseline. |

The shared Phase 1 contracts intentionally remain Python 3.9 compatible so deterministic local
validation is possible. Production promotion remains gated by the CI Python 3.11 job.
