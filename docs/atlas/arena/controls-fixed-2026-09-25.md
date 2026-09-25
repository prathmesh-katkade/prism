# Fixed-harness preflight controls — 2026-09-25

AtlasBench V1 remains byte-for-byte unchanged, with hash
`f0af1e39a778755a925f70570c19a4e5754e2dcccbb57d44e8673627a7f4f10f`.
Its authored correct-index counts are 8/81/1/0. Under seed
`atlasbench-shuffle-v1`, presented correct-index counts are 23/24/20/23.
A constant index-1 control scored 81/90 before shuffling and 24/90 after.

The four model controls below used the same shuffled choice order and exact
choice-string JSON Schema. Both envelopes retained temperature 0,
`think: false`, `num_predict: 256`, and `num_ctx: 4096`.
Prose listed the choice strings without A/B/C/D labels.

| Model | Nested JSON correct / parsed wrong / invalid | Prose correct / parsed wrong / invalid |
| --- | ---: | ---: |
| `phi4-mini:latest` | 90 / 0 / 0 | 90 / 0 / 0 |
| `olmo-3:7b-instruct` | 88 / 2 / 0 | 90 / 0 / 0 |

Every request ended with `done_reason=stop`. Nested policy ID:
`2567d704bfb69b3335a93a47e0b4ecf817522c1fd71c4c8504c27080741dd531`.
Prose policy ID:
`3e34088c681eb5c09fb0125501eebf57ce7244e958cc4b1da65d997ce647a3ac`.

Durable run IDs: Phi nested `benchrun_e02fcc3bc141422084bc0743030bd645`;
Phi prose `benchrun_b0993dfcde1b4fc1ab582137fbccd4ad`;
OLMo nested `benchrun_427e3a8ae06948dfa6c3bbb7374c9366`;
OLMo prose `benchrun_1d11cd1dd74a44feb2695bf0061fe5f5`.

The former opposite-direction envelope effect does not persist under the
combined shuffle-and-string policy. Phi has no observed envelope difference;
OLMo's two-item difference on 90 items is too small to establish one. These
controls do not isolate the effect of the string schema from the shuffle.
They do show the former index-based results are invalid for capability
ranking. A direct Phi check of one item each authored at indices 0, 1, and 2
confirmed that the chosen string mapped through the stored permutation to
the correct original index.
