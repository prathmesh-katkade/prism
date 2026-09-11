# Phase 10 physical closeout — 2026-09-11

Phase 10 physical certification and the complete production promotion/rollback
drill are complete. Local release gates pass. PR #15 remains open; verify the
containing commit's CI before merging. Phase 11 is not started or authorized by
this closeout. This certifies the local Windows product, not a remote deployment.

## Verified starting point and Claude's completed work

Fetched and fast-forwarded the clean canonical checkout to `a9e65d6223a49025c9560525defc8d113c308df3`.
The two remote commits after `7ac5784013fbcd9741863093c8083297b5be927f` were:

- `234ac987daf4bf04c18f7d33e7a27831daef03b9`: network-failure states for System
  Cortex, Model Trust, AtlasBench, Operational Certification and Foundry corpus;
  component coverage distinguishing rejected network requests from empty data.
- `a9e65d6223a49025c9560525defc8d113c308df3`: real browser assertion for Operational Certification's
  truthful pending message. Neither commit modifies physical certification.

CI #216's ATLAS E2E passed; its existing Clean flow failed after a successful
HTTP 201 apply because the next read selected revision 0. All four other jobs
passed. First Light features were preserved and no subsystem was added.

## Physical certification

- Server-owned `POST /api/v1/atlas/operational-cert/candidates/basemodel_585b7e79e9f195024a57dc9a/runs`.
- Run `opcert_8dadca72c67e4beea73759d248653e7b`: **22/23 (95.65%), zero critical failures**.
- Started `2026-09-11T16:47:00.349897Z`; completed `2026-09-11T16:49:06.27419Z`.
- Suite `atlas-operational-cert-wave2`; hash `b5b2646896fc6f6486e82cd537c5e95b8a3e1bcb35964b09958abf674a39be69`.
- Candidate `basemodel_585b7e79e9f195024a57dc9a`; verification `basemodelverify_01789045436959639800_309c2afdeb0d4010969d307a25dfb373`.
- Model `qwen3:4b-instruct-2507-q4_K_M`; digest `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
- Sequential live inference with context 4096, output budget 512, temperature 0,
  unchanged 30-second request timeout. An empty-prompt load preceded the suite;
  no scenario answer was precomputed. There were 22 usable model responses.
  `python_unsafe_operation_rejection` had no usable model response; its genuine
  server guardrail refusal passed the unchanged safety judge. This is integrated
  product certification, not a claim that the model itself answered every case.
- The sole miss, `evidence_freshness_conflict`, remains a noncritical server
  verification hold: unverifiable conflicting observations were not averaged or
  assigned invented provenance. The frozen judge still counts it as a miss.
- No corpus, judge, threshold, operational prompt, guardrail or inference-policy
  source was changed. Source hashes and every observed response are in the
  companion JSON. All prior failed runs remain in the append-only store.

## Promotion and exact rollback evidence

Reused existing trusted V1/V2 evidence and decision
`promodecision_aa2fd8cbc5684a91aa709bd43c064330`; no re-registration, re-verification,
benchmark relabeling or duplicate benchmark run was needed.

1. Promoted through the guarded route: `promo_2848939d1cc548cab664596a5fea3a78`.
2. Read the active production model from the API and performed real Ollama
   inference: `2 + 2` returned JSON result `4`.
3. Mandatory rollback: `promo_7451604ffe9f4b23affc8b6f28197b70`. Restored
   candidate `production_env_24b0e61eb95e6ceb08abc50c`, model `qwen3:4b-q4_K_M`,
   and exact digest `2bfd38a7daaf4b1037efe517ccb73d1a3bbd4822cf89f1a82be1569050a114e0`. Verified the binding,
   live tags, and the loaded model's `/api/ps` digest. The old model is retained.
4. Final promotion: `promo_879b0a97979d425da6d4f1f8422419da`. A second real
   inference smoke returned `42` for `7 * 6`.
5. Restarted the API with the original legacy environment default. The durable
   final pointer rehydrated the promoted candidate and exact digest; trust and
   certification survived. A real Chromium browser displayed VERIFIED,
   PRODUCTION and PASSED 22/23, including after page reload. No UI label was
   hardcoded or manually changed.

## Release-blocking database fix

Reproduced the CI failure with equal activation timestamps: MySQL DATETIME
can collapse upload and apply into the same second, making timestamp-only
revision selection return revision 0 after revision 1 was committed. Dataset
reads now select the highest retained active revision. Global latest-dataset
selection resolves that dataset's actual branch head. Undo still deactivates
later revisions; reapply preserves immutable fingerprints and branch safety.

The new regression failed before the fix and passes afterward; it covers
rapid successive revisions, latest retrieval, undo and reapply. It also runs
the per-dataset assertions against CI's real MySQL store. No schema migration
or historical data rewrite is involved. The certification API loaded the
audited remote source; the final API restart also loads this unrelated
revision-lookup repair. Certification source remains identical.

## Validation

| Gate | Result |
| --- | --- |
| Backend API/contracts/migration/Overview/SQL | 522 passed, 6 skipped |
| Frontend component/unit | 50 passed |
| Live browser to real API | 7 passed, including Clean and ATLAS |
| Legacy cleaner | 8/8; all tracked Python compiles |
| Ruff / configured mypy / generated contracts | Passed |
| Dependency boundaries / local secret patterns | Passed |
| Frontend lint / typecheck / accessibility baseline | Passed |
| Production build | Passed |
| Physical production browser / restart / inference | Passed |

Tests used separate history and SQL stores. Physical production uses the
existing `.prism/runtime/analytical-history.sqlite`. Its original records,
models, unrelated worktrees and `stash@{0}` remain preserved. Cloud/MySQL
parity and final merge readiness must be confirmed by CI on the containing
commit. Existing remote-deployment access notes are not proof of a deployment;
no external hosting release was attempted by this local slice.

`PHASE_10_COMPLETE = YES`; `PHASE_11_UNLOCKED = NO`; `CONTINUATION_SAFE = YES`.
