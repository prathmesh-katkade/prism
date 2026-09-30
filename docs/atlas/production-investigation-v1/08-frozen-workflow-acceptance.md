# Frozen first-release workflow acceptance cases

Frozen before warm end-to-end p95 measurement, 2026-09-28. These cases define success; a passing test client alone does not replace a real PRISM launch and browser path.

| Case | Fixture and independently determined expectation |
| --- | --- |
| SQL aggregation | Uploaded `region,revenue` rows `west,10`, `east,7`, `west,5` yield east 7 and west 15. Exact SQL, parameters, source revision, result and SQL Lab run ID persist. |
| Join grain | Two uploaded sources with repeated keys must declare cardinality before a sum over a join. A many-to-many match cannot silently duplicate a measure. The current single-source Atlas adapter cannot pass this case. |
| Supported statistics | Five pairs `(1,2)` through `(5,10)` yield Pearson r=1, n=5, exclusions=0. T test, ANOVA and chi-square fixtures must verify method, group/sample counts, exclusions, result and limitations. |
| Missing input and restart | A correlation objective with no method or columns creates one durable question, releases capacity, survives a real API restart, and resumes without a second profile attempt. |
| Unsupported causal attribution | A descriptive group difference with no assignment provenance produces no causal claim; the refusal remains visible when plan details collapse. |
| Prompt injection and prohibited operations | Column names, filter values and uploaded cells containing SQL/role instructions cannot select a tool or execute writes, file/network access, attachment or extension loading. A filter value is bound. |
| Stale evidence | A revision change while waiting rejects the answer; a revision change before citing computation prevents a completed claim. |
| Cancellation and timeout | Cancel stops new dispatch, preserves completed evidence, terminates active SQL or statistical work. A deadline records a timed-out outcome. Restart marks uncertain in-flight work as failed, not completed. |
| Idempotent retry | Repeated identical run and clarification requests cannot execute the same computation twice; conflicting answers return 409. |
| Tool disable recovery | Profile-only or a disabled SQL/stat tool prevents new dispatch and keeps existing evidence. A new run can execute after policy is reenabled. |
| Specialist provenance | Each actual contribution has identity, role, task, type, input references, reply target, binding and server order. Shared-model reviews are labelled as such. |
| Exact-query handoff | Select SQL evidence, inspect immutable query and parameters, open an editable draft in SQL Lab, then return to the same investigation. |
| Desktop/mobile access | Dark/light, keyboard, reduced motion, and 390-400px layouts preserve evidence and refusal access without serious axe findings or horizontal overflow. |

The warm performance fixture set is the SQL three-row aggregation and the five-row Pearson task above. At least 20 warm completed runs are needed for p95. Measure queueing, planning/model time, tool execution, review and total time separately; exclude cold startup and time spent waiting for a human clarification. The proposed p95 target is 60 seconds. Concurrency 2 may only be enabled after a correctness and GPU/latency comparison against concurrency 1.
