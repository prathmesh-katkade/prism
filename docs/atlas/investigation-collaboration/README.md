# Atlas investigation and collaboration proof

These captures were made with isolated test databases. `01` shows an actual persisted Atlas run against an uploaded three-row CSV; its SQL step was blocked because a named SQL Lab connection and reviewed query were absent. The run completed, while the causal question remained unresolved. `02`–`08` use explicitly labelled illustrative data. No sample message or count represents a model or tool execution.

| File | View |
| --- | --- |
| `01-investigation-real-run.png` | Persisted plan, output, and execution refusal |
| `02-collaboration-sample-objection.png` | Sample work map, exchange, and open objection |
| `03-selected-sample-evidence.png` | Selection in PRISM's shared inspector |
| `04-sql-handoff-unavailable.png` | Exact-query action disabled because SQL and source reference were not persisted |
| `05-empty-dark.png` | Empty investigation |
| `06-dark-theme.png`, `06-light-theme.png` | Both themes |
| `07-mobile-sample.png` | 400px layout |
| `08-large-sample-200-tasks.png` | 200-task scale check |
| `09-interaction.webm` | Sample record selection and recorded-event stepping |

The current run contract supports plan and step state, evidence records, council conclusions and objections, and an ordered event journal. The new append-only intervention API stores targeted human notes. It does not establish a general specialist message stream, historical reply links, claim-level support edges, exact Atlas SQL provenance, or reconstructable historical snapshots. The UI leaves those relationships absent, labels the sample, and uses an event log for stepping. See [ADR 0020](../../architecture/adr/0020-atlas-investigation-collaboration-projection.md) for the source matrix.

Verification output, including initial live-browser failures and the passing rerun after the callback fix, is appended to `C:\Users\Admin\Documents\atlas-gui-log.txt`.
