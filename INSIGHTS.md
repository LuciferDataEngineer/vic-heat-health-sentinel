# What the next fortnight means for Victorian heat and health

Snapshot accessed 9:24 am, Saturday 31 October 2026, Melbourne time. Temperatures are the Open-Meteo forecast and the ERA5 archive at one interior point in each of 80 local government areas. Population figures are the 2021 Census. This is a planning aid. It is not a medical forecast and it does not predict deaths.

## The decision

Do not open cooling centres for this forecast. Use the quiet fortnight to get the summer roster and the welfare lists ready, starting with Mildura, Greater Bendigo, Greater Geelong, Campaspe and Moira.

No Victorian area is forecast to reach 35°C between Saturday 31 October and Saturday 14 November 2026. That means **0 people aged 65 and over** are living in an area with a dangerous-heat day in the next 16 days. The same is true of the stricter health-alert test (a hot day followed by a night that stays warm): no area meets it.

The hottest single reading in the forecast is **31.2°C in Swan Hill on Monday 2 November**. A usual high in Swan Hill on that date, averaged over 2016–2025, is **27.7°C**. The day is warmer than usual for that town, and it is still short of 35°C.

For a typical Victorian, weighting each area by its population, daytime highs across the fortnight are **2.2°C cooler than the same dates in 2016–2025**. Saturday 31 October itself is a little warmer than usual (about 21°C against a usual 19°C). The cooler days are the ones after that.

Air is not a problem in the coming days. No area reaches the Australian daily standard for fine particles (25 µg/m³) or the eight-hour ozone standard (about 130 µg/m³). The highest daily fine-particle average in the outlook is about 11 µg/m³, in Wodonga. The highest eight-hour ozone is 71 µg/m³.

## Where to prepare before December

The priority list is not "where it is hot next week". Next week is not hot. It is where a hot summer and a vulnerable community overlap, so the first real heatwave has somewhere to land.

The ten areas to prepare first, and the people aged 65 and over who live there:

| Area | Priority | People 65+ | Typical summer days of 35°C or more | Hottest day in this forecast |
| --- | ---: | ---: | ---: | --- |
| Mildura | 32.5 | 11,168 | 32.4 | 30.4°C |
| Greater Bendigo | 31.7 | 24,141 | 11.2 | 25.1°C |
| Greater Geelong | 30.5 | 53,234 | 5.7 | 23.8°C |
| Campaspe | 30.1 | 9,617 | 17.6 | 27.3°C |
| Moira | 29.8 | 8,366 | 18.8 | 29.0°C |
| Greater Shepparton | 29.7 | 13,118 | 14.3 | 26.9°C |
| Brimbank | 28.8 | 31,686 | 8.0 | 24.0°C |
| Gannawarra | 28.1 | 3,221 | 25.0 | 29.6°C |
| Greater Dandenong | 26.9 | 24,871 | 6.6 | 25.0°C |
| Darebin | 26.8 | 21,871 | 8.2 | 24.7°C |

Together those ten areas are home to **201,293 people aged 65 and over** and about 1.10 million residents. That is roughly one in six older Victorians. The state's 2021 population on these boundaries is 6.49 million, of whom 1.09 million are 65 or older.

Read the two columns separately:

- Mildura, Gannawarra, Moira, Campaspe and Shepparton are on the list because summer is genuinely hot. Mildura averages **32 days of 35°C or more** each summer (November to March, 2016–17 through 2025–26). The unweighted average across all 80 areas is **7.8 days**.
- Greater Geelong, Brimbank, Greater Dandenong and Darebin are on the list because so many older people live there. Geelong averages only 5.7 days of 35°C, but 53,234 people aged 65 and over live there. A single hot day in Geelong touches more older people than a week of heat in a small shire.
- Gannawarra shows the other end of that trade-off: 25 days of 35°C in a typical summer, and 30% of residents are 65 or older, but the headcount is 3,221. It needs a welfare list more than a surge roster.

The ten areas with the most 35°C days, regardless of population, hold **57,211 people aged 65 and over**. That is the north-west and the northern river towns: Mildura, Swan Hill, Gannawarra, Buloke, Yarriambiack, Loddon, Moira, Hindmarsh, Campaspe and Greater Shepparton. Those are the places where cooling centres will open again and again.

## What "dangerous heat" means here

On the public page, a dangerous heat day is a day when the maximum reaches **35°C**. That is the figure people and councils already use.

There is a stricter figure behind the scenes, taken from the temperature levels the Victorian Department of Health published for each forecast district. It averages today's maximum with the next night's minimum, and compares that with 34°C in the Mallee, 32°C in the Wimmera, Northern Country and North East, and 30°C elsewhere. A day counts only when the night stays warm as well. Across ten summers that test fires rarely: about **0.5 days per area per summer** on average, against 7.8 days of 35°C. In Mildura the health-alert test averages 1.7 days a summer, while days of 35°C average 32.

Both showed up in the January 2019 heatwave at the Mildura sample point. The high was **45.7°C on 16 January 2019**, the health-alert test was met on the 15th, 16th and 24th, and the Bureau's excess-heat calculation reached the severe band on several of those days. The warehouse and a separate implementation of that calculation agree on this month to well under a thousandth of a degree. The public page does not mention the excess-heat calculation. It is the cross-check, not the headline.

Yarriambiack Shire sits across the Mallee/Wimmera boundary. The whole shire is given the lower Wimmera level (32°C) so the southern half is not missed. Unincorporated Victoria is the one area without a published council match; it is given the Central level of 30°C and flagged as a fallback. It has fewer than a thousand residents and does not move the ranking.

## The one-day-ahead check

The page uses the weather forecast for the next 16 days. Separately, a small model asks a harder question: using only the weather up to yesterday, how often can we tell that today's maximum will reach 35°C?

It is a gradient-boosting classifier. The inputs are yesterday's temperatures, the average of the last three and seven days, the time of year, the area's location, and that area's own hot-day climate estimated only on summers before November 2022. Today's temperature is not an input.

Training summers are November 2016 to March 2022 (79,280 area-days). Test summers are November 2022 to March 2026 (48,400 area-days). About **5.2%** of those summer days reached 35°C in both periods.

On the test summers:

| Estimate | ROC AUC | Average precision | Brier score (lower is better) |
| --- | ---: | ---: | ---: |
| This model | 0.88 | 0.30 | 0.042 |
| "It was 35°C yesterday" | 0.63 | 0.12 | 0.074 |
| "How often this area is hot in this month" | 0.72 | 0.14 | 0.048 |

Average precision is the right headline because most days are not hot. A useless estimate that always says "no" would score near 0.05, the share of hot days. The model is clearly better than persistence and better than the month-by-area rate. It is not magic. The strongest input is yesterday's maximum, then the area's own climate. Heat comes in spells, and some areas are simply hotter. That is what the model has learned.

It is not used in the priority number on the page. The 16-day forecast is a better guide to next week than a one-day statistical guess. For the first forecast day, 31 October, the model's chance of a 35°C day in Mildura is about 10%, and the forecast high there is 30°C. They agree that it is not a dangerous-heat day.

A drift check compared 12,000 training summer days with 12,000 later summer days across the same 11 inputs. **No dataset drift, and none of the 11 inputs drifted.** The later summers still look like the earlier ones on these features. That does not say the climate is unchanged against a 1971–2000 baseline. The whole record used here is already the recent climate, 2016–2025.

## How the priority number is built

It is a weighted index from 0 to 100, not a trained prediction of illness.

- 34% — is dangerous heat actually in the next 16 days, and how close is the hottest day to 35°C?
- 16% — is this fortnight warmer or cooler than usual?
- 20% — how many older people times how many 35°C days a typical summer brings
- 22% — the share of residents 65 and over, children under 5, households where someone lives alone, and households on less than $500 a week (2021 dollars, including no income)
- 8% — days in the air-quality outlook above the Australian fine-particle or ozone standard

In this snapshot the first, second and last pieces are near zero for almost everyone, because the fortnight is mild and the air is clean. The list is therefore the summer-and-community list. When a real hot spell enters the 16-day forecast, the heat piece will lift the areas that are actually about to cook, and the page status will change from "Quiet fortnight" to "Prepare now".

## What would change the advice

A day of 35°C anywhere, or a health-alert night in the Mallee or the north, would put older residents of that area into the first number on the page and would be a reason to open cooling centres. Until that appears, the work is lists, venues and rosters, not activation.
