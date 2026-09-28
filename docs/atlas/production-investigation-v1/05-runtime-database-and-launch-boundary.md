# Runtime database and launch boundary

Status: direct read-only source inspection and disposable-copy startup test,
2026-09-28. This report does not reconstruct when source migrations occurred.

## Designated desktop history store

The designated SQLite file is
`C:\Users\Admin\source\repos\prism\apps\api\.prism\runtime\analytical-history.sqlite`.
A direct SQLite read-only connection (`mode=ro`) returned `ok` from
`PRAGMA integrity_check` on 2026-09-28. It found **39 tables**, whereas the
earlier local report recorded 38. This difference is unresolved. Direct SQL
read the two pointer rows: sequence 0 is
`production_env_e77dbfc3de7584a8c502a6f8`; sequence 1 is the current fast
pointer `basemodel_585b7e79e9f195024a57dc9a`, bound to
`qwen3:4b-instruct-2507-q4_K_M`, the previous candidate
`production_env_e77dbfc3de7584a8c502a6f8` bound to `qwen2.5:3b`, two
promotion events, and no deep pointer. Directly read runtime binding digests
were `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`
and `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`.
No pointer change is authorized.

The audit before this investigation found no `tier` column in the designated
source; a subsequent inspection found one. The intervening schema change is
real, but its exact cause and time have not been established. Constructing
durable store classes may execute additive migrations, so a store constructor
is neither a read-only probe nor proof that the whole API restarted cleanly.
Do not infer an earlier migration history or claim that no drift occurred.

## Local backup

The SQLite backup API produced a local snapshot at
`docs/atlas/production-investigation-v1/backups/analytical-history-20260928T065043Z.sqlite`.
It is **untracked and must remain local**. SHA-256:
`03bbc35cb97e84abc1a92d54a9f5fbeb3592d5b208c6d0c01d397afdffcc6afc`.
Prior inspection reported `PRAGMA integrity_check = ok` on the snapshot.
Its byte hash need not match the source because SQLite's backup API creates a
consistent logical copy. The backup must be preserved; migration and restart
tests should use another disposable copy of it.

Earlier local work instantiated eight durable store classes on the backup and
reported no exception. That is evidence about constructor and migration paths
on that backup only. A complete API restart with the explicit database URL has
not been demonstrated here. In particular, the observed `tier` change means
the designated source cannot be described as untouched by migrations.

## Launch configuration

For desktop use, set `PRISM_ANALYTICAL_HISTORY_DATABASE_URL` to an absolute
SQLite URL for the intended durable store, and launch from this supported
checkout with `--env-file apps/api/.env`. The URL must be explicit because the
fallback `.prism/runtime/analytical-history.sqlite` depends on process cwd.
Do not launch an abandoned checkout against the designated store.

Hosted deployment has a different boundary: configure a managed database URL
through the hosting environment and set `PRISM_REQUIRE_DURABLE_HISTORY=true`.
The local desktop SQLite path is not a hosted deployment setting.

The repository's `apps/api/.env.example` and `apps/api/README.md` document the
intended startup command. Their edits alone are not a successful startup test.
The actual uvicorn command was launched twice with `--env-file` pointing to a
**disposable copy** of the local backup. Both processes reached
`/api/v1/platform/ready`; the promotion pointer response was identical. The
first process uploaded a three-row CSV and ran a typed SQL aggregate through
Atlas; the second recovered the identical durable run and revision 0 profile.
The independently calculated SQL totals were east 7 and west 15, matching the
recorded rows. The supplied backup hash was unchanged before and after.
Raw API outputs and server logs are in `verification/`; the reproducible test
driver is `tools/verify_atlas_disposable_startup.py`. This verifies the
disposable startup path, not a launch against the designated source file.

## Rollback boundary

Rollback was documented but not executed. A model rollback appends a new
promotion event and therefore requires a separate instruction. First confirm
the current pointer and prior binding through the promotion endpoints; then
use the rollback endpoint with a recorded reason and verify the pointer after
restart. A code rollback must use a compatible revision and preserve the
durable database. This investigation makes no model promotion, rollback, or
production pointer change.
