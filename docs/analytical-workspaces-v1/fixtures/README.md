# Non-sensitive acceptance fixtures

These CSVs are synthetic and deterministic. Expected outcomes are declared before interpretation:

| Fixture | Expected facts |
|---|---|
| `business-export.csv` | 5 uploaded rows, 4 columns, one exact duplicate of `c1`, one missing `revenue`, 4 rows after duplicate removal. The two retained North rows include one missing revenue; the two South rows sum to 50. |
| `scientific-observations.csv` | 4 rows. `01/02/2025` and `02/01/2025` are ambiguous without an explicit day/month format; `13/02/2025` is valid with `%d/%m/%Y`; `31/02/2025` is invalid for either day/month reading. One `measurement` cell is nonnumeric (`invalid`). |
| `public-style-categories.csv` | 6 rows, 3 districts and 2 years. Total `requests` = 614; total `completed` = 554. No missing cells. East Transit requests rise from 88 to 101. |

The generated 100,000-row fixture, exact outcomes, sampling caps and measured times are in [`../performance-100k.json`](../performance-100k.json) and [`../performance-100k-ui.json`](../performance-100k-ui.json).
