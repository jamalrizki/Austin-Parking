# Real-world spot checks

Blocks checked against what is actually posted (on foot or Google Street View) and logged here.
Any mismatch: fix the rule, or force the block grey and note why.

| # | Date checked | Street, block, side | Map said (day/time viewed) | Signs say | Match? | Action |
|---|---|---|---|---|---|---|
| 1 | 2026-11-08 (Jamal, on foot) | La Calma Dr, 6100 block, both sides | One side green ("no parking signs") | No parking on either side; no space at the curb | No | Divided road, not in CTN (no width/lane data). Green now requires a listed parking lane or >= 28 ft pavement; this side is now grey "room unconfirmed". |
| 2 | 2026-11-08 (Jamal, on foot) | La Posada Dr, 1000 block, both sides | One side green ("no parking signs") | No parking on either side; no space at the curb | No | Same cause and fix as #1. Other sides were already red from city No Parking signs. |
| 3 | 2026-11-08 (Street View, Mar 2024; Jamal confirmed) | E 35th St, 100 block, north side (104 E 35th) | Permit sign "No parking 8AM-5PM Mon-Fri except with area permit" applied to the whole side, so free outside those hours | Frontage at 104 is an apartment parking-lot apron / curb cut (no parking there), but further down the same side there is curb parking | Partly |  Sign rules apply to the whole block side; driveway/curb-cut frontage isn't modelled. Fix: measure curb gaps between driveways/lots (city impervious-cover survey) and show "room for about N cars"; side turns red only if no gap fits a car. |

## 2026-11-10: Street View survey of 20 random green sides

Random sample (seed 2026) of the map's green claims after commit 347a767: 16 whole block sides
green because the city recorded no restriction signs, and 4 green stretches of sides split by sign
arrows. At each, Street View looking along that curb in both directions from mid-block. Checked
by Claude; the image capture date is what was seen, not today. Street View covers roughly 50-100 m
from the viewpoint, so long blocks were only partly seen.

| # | Street View image | Street, block, side | Map said | Seen | Match? |
|---|---|---|---|---|---|
| 4 | Jan 2022 | Wilcrest Dr 2700, south | Green, no signs | Residential, car parked at curb, no signs | Yes |
| 5 | Jan 2025 | Bridgeway Dr 1400, north | Green, no signs | Residential, no signs (hydrant across the street) | Yes |
| 6 | Jun 2019 | Evans Ave 4800, east | Green, no signs | Residential, cars parked, no signs | Yes |
| 7 | Feb 2024 | Northern Dancer Dr 6100, north | Green, no signs | Residential, no signs | Yes |
| 8 | Apr 2024 | Bowerton Dr 1600, south | Green, no signs | Residential, cars parked along curb, no signs | Yes |
| 9 | Apr 2024 | Majorca Dr 10000, north | Green, no signs | Residential, no signs | Yes |
| 10 | May 2011 | Meridian Park Blvd 12700, west | Green, no signs | Only image is from 2011: road unfinished, barricaded | Can't tell |
| 11 | Jan 2025 | Black Granite Dr 3500, east | Green, no signs | Residential, cars parked both sides, no signs | Yes |
| 12 | Apr 2024 | Edgefield Dr 6700, east | Green, no signs | Institutional frontage, no signs | Yes |
| 13 | Apr 2022 | Briarwood Ln 8200, west | Green, no signs | Residential, cars parked, no signs | Yes |
| 14 | Mar 2024 | Laird Dr 6600, west | Green, no signs | Residential, cars parked, no signs | Yes |
| 15 | Sep 2019 | Tower Trl 5200, east | Green, no signs | Red-painted curb (no parking) along part of the side around a fire hydrant; rest open, no signs | Partly |
| 16 | Apr 2024 | Cindy Ln 2400, north | Green, no signs | Residential, no signs | Yes |
| 17 | Oct 2024 | Reedsport Trl 12000, east | Green, no signs | Residential, no signs (stop sign on the other corner) | Yes |
| 18 | Feb 2024 | Lonesome Valley Trl 5900, west | Green, no signs | Residential, no signs | Yes |
| 19 | Jan 2025 | Timbrook Trl 11200, north | Green, no signs | Back fences, hydrant, no signs | Yes |
| 20 | Apr 2024 | Ortman Dr 3000, north (arrow-split stretch) | Green stretch | Cars parked along it, no signs | Yes |
| 21 | Feb 2022 | Ember Glen Dr 10200, south (arrow-split stretch) | Green stretch | No signs on this curb; sign pole across the street by the school | Yes |
| 22 | Apr 2024 | Secrest Dr 5800, west (arrow-split stretch) | Green stretch | Residential, no signs | Yes |
| 23 | Mar 2024 | West Ave 3200, east (arrow-split stretch) | Green stretch | Commercial frontage; posts are utility boxes, no parking signs | Yes |

Result: 18 match, 1 partly (painted red curb not in any city dataset checked: the markings
inventory's 902 painted curbs do not include it), 1 can't tell (no Street View since 2011).
With 19 decidable sides, a 1-in-19 partial miss is consistent with a false-green rate anywhere from
~0% to ~25% (95% interval); a larger sample would narrow that.
