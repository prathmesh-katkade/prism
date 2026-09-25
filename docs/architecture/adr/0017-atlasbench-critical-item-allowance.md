# ADR 0017: AtlasBench critical-category item allowance

Status: Accepted, 2026-09-25

## Context

AtlasBench V1 has only eight to ten items in each critical category. The
existing zero-tolerance comparison of category pass rates treats one wrong
item as an 10–12.5 percentage-point regression and rejects a candidate. That
resolution is too fine for this small category sample. This is a fixed policy
choice, not a statistical significance test or a response to any candidate's
new verdict.

## Decision

For the frozen V1 corpus, a critical-category regression requires the
candidate to get at least **two fewer items correct** than production in that
category. A one-item difference is allowed. Categories and their membership
remain unchanged. A candidate that gets fewer items correct **overall** than
production is still rejected, regardless of category allowance. An equal or
higher overall score with no critical-category regression is promotion
eligible; all other independent promotion gates remain required.

The allowance is represented as an integer in the evaluation policy identity,
with a new policy version. Existing durable Round 5 runs retain their original
policy IDs and are never rewritten. They may be read and re-adjudicated under
this documented rule because their corpus, prompts, output schema, shuffle,
and inference settings match each other. Future runs carry the new policy ID,
so old and new policy generations are not silently mixed by the promotion
route.

## Consequences

One item in a short category no longer vetoes an otherwise qualifying run.
Two missing items still do. The overall-score guard prevents the allowance
from admitting a candidate that is worse across the 90-item suite. This rule
was fixed before computing its effect on the stored Round 5 model rows.
