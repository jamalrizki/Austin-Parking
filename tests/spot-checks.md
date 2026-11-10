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

## 2026-11-10: Street View survey of 40 more green sides (after commit c984918)

Same method, new random sample (seed 7331, none of the streets above): 30 whole sides green for "no
signs recorded", 10 green stretches of arrow-split sides. Images older than 2015 count as "can't
tell".

| # | Street View image | Street, block, side | Map said | Seen | Match? |
|---|---|---|---|---|---|
| 24 | Jan 2025 | Winfield Dr 3400, west | Green, no signs | Residential, no signs | Yes |
| 25 | Jan 2022 | Audrey Ct 1000, south | Green, no signs | Residential, cars parked, no signs | Yes |
| 26 | Mar 2024 | Reese Ln 7000, east | Green, no signs | Residential, cars parked, no signs | Yes |
| 27 | Jan 2025 | Campden Dr 2300, south | Green, no signs | Residential, cars parked, no signs | Yes |
| 28 | Feb 2025 | Gaines Mill Ln 7600, east | Green, no signs | Residential, no signs | Yes |
| 29 | Jan 2025 | Teri Rd 4600, south | Green, no signs (city lists a parking lane) | Rebuilt street: yellow posts are a centre median, bike path behind the curb; wide curb lane, no signs; whether parking is marked there isn't visible | Can't tell |
| 30 | Apr 2024 | Mountain Quail Rd 9400, east | Green, no signs | Residential, cars parked, no signs | Yes |
| 31 | Feb 2022 | Alex Ln 9400, west | Green, no signs | Residential, no signs | Yes |
| 32 | Apr 2024 | Iveans Way 14500, north | Green, no signs | Residential, no signs | Yes |
| 33 | Feb 2025 | Twilight Mesa Dr 7300, south | Green, no signs | Along a greenbelt fence, no signs | Yes |
| 34 | Nov 2019 | Foggy Mountain Dr 8700, north | Green, no signs | Residential, no signs | Yes |
| 35 | Jan 2025 | Breckenridge Dr 4100, west | Green, no signs | Residential edge, no signs | Yes |
| 36 | Mar 2024 | Grover Ave 6300, east | Green, no signs | Residential; one bare post, no sign plate | Yes |
| 37 | Apr 2024 | Saber Creek Trl 8500, west | Green, no signs | Residential; stop sign at the corner only | Yes |
| 38 | Jun 2019 | Mc Bee St 2300, south | Green, no signs | Townhouses, cars parked, no signs | Yes |
| 39 | Jan 2025 | St Stanislaws Dr 1100, south | Green, no signs | Residential, cars parked, no signs | Yes |
| 40 | Apr 2024 | Big Cat Cv 6300, east | Green, no signs | Residential cove, no signs | Yes |
| 41 | Jan 2025 | Sunridge Dr 2600, west | Green, no signs | Cars parked at the curb, no signs | Yes |
| 42 | May 2022 | Rusty Ridge Dr 6500, west | Green, no signs | Hillside residential, no signs | Yes |
| 43 | Feb 2020 | River Oaks Trl 11700, east | Green, no signs | Residential, no signs | Yes |
| 44 | Jan 2025 | Crosstimber Dr 11600, east | Green, no signs | Residential, no signs | Yes |
| 45 | Nov 2019 | Seneca Falls Dr 10600, east | Green, no signs | Subdivision entrance; stop sign only | Yes |
| 46 | Jan 2025 | Kasper St 6100, north | Green, no signs | Residential, no signs | Yes |
| 47 | May 2007 | Kromer St 8300, east | Green, no signs | Only image is from 2007 (no signs then) | Can't tell |
| 48 | Feb 2024 | Peggie Nell Dr 7500, west | Green, no signs | New subdivision, no signs | Yes |
| 49 | Mar 2024 | Hillcrest Ln 1700, east | Green, no signs | Residential, cars parked, no signs | Yes |
| 50 | May 2019 | Stillwood Ln 8500, west | Green, no signs | Residential, no signs | Yes |
| 51 | Feb 2024 | Bridge Point Pkwy 7600, west | Green, no signs | Wooded frontage; stop sign at the corner only | Yes |
| 52 | Feb 2025 | Nasoni Cv 6400, south | Green, no signs | Residential cove, no signs | Yes |
| 53 | Apr 2024 | Thornridge Rd 1300, north | Green, no signs | Residential, cars parked, no signs | Yes |
| 54 | Jan 2025 | Curlew Dr 9800, east (stretch) | Green stretch | School fence, no signs on this curb (sign posts across the street) | Yes |
| 55 | Mar 2024 | E 34th St 300, south (stretch) | Green stretch | Car parked on it, no signs on this side | Yes |
| 56 | Mar 2024 | Burns St 6200, east (stretch) | Green stretch | Hand-made private "No Parking" signs on a fence (not street rules); the only city sign is a speed-limit sign | Yes |
| 57 | Feb 2024 | Mc Neil Dr 9400, north (stretch) | Green stretch | Cars parked along it, no signs | Yes |
| 58 | May 2019 | Quicksilver Blvd 2500, south (stretch) | Green stretch | Residential, no signs | Yes |
| 59 | Feb 2021 | E 3rd St 2000, north (stretch) | Green stretch | Park frontage, cars parked, no signs | Yes |
| 60 | Mar 2024 | Northland Dr 2200, south (stretch) | Green stretch | Street-name sign only | Yes |
| 61 | Mar 2019 | E 43rd St 300, south (stretch) | Green stretch | Truck parked on it, no signs | Yes |
| 62 | Apr 2022 | Mairo St 400, south (stretch) | Green stretch | Image almost entirely blurred | Can't tell |
| 63 | Apr 2024 | Scotland Well Dr 10400, north (stretch) | Green stretch (city lists parking lanes, "P-T-CL-T-P") | A narrow marked lane with an arrow along the curb that looks like a bike lane; no cars, no signs | Possibly not |

Result: 36 match, 1 possibly not (Scotland Well Dr: Street View and the city's lane record
disagree), 3 can't tell.

**Combined, 60 checked:** 54 match, 1 partly (painted curb), 1 possibly not, 4 can't tell.
Counting both doubtful ones as errors, 2 of 56 decidable = 3.6% (95% interval 0.4%-12.3%);
counting only the confirmed partial miss, 1.8% (0.0%-9.6%). No green side or stretch had an official
parking-restriction sign that the map missed.
