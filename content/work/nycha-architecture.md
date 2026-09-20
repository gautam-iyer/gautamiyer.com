---
title: "The Architecture of NYCHA"
date: 2026-07-08
subtitle: "How New York built the largest stock of public housing in America — and how the building stopped. 1935–2010, in five charts."
form: "Data Analysis"
when: "July 2026"
where: "New York City"
summary: "Construction waves, tower heights, superblock footprints, building scale, and per-room costs, from NYCHA's development data book."
method: "Era pivots over NYCHA's Development Data Book (346 developments, January 2025 vintage), plus development-level OLS regressions of building height on completion year."
datanote: "Source: NYCHA Development Data Book, January 2025 vintage, pivoted by completion era. \"New construction\" excludes rehabs and acquisitions. Later eras thin out: after 1995 NYCHA completed only a handful of developments, so era averages there reflect one or two projects. Costs are nominal (not inflation-adjusted). Preliminary analysis — a fuller write-up is coming."
featured: true
order: 1
stats:
  - label: "Developments"
    value: "346"
  - label: "Apartments"
    value: "183,141"
  - label: "Residential buildings"
    value: "2,465"
  - label: "Built 1945–1965"
    value: "63%"
scripts:
  - "js/vendor/chart.umd.js"
  - "js/charts.js"
  - "js/work/nycha.js"
  - "js/lightbox.js"
aliases: ["/projects/nycha-architecture/"]
---

NYCHA opened First Houses on the Lower East Side in 1935. Over the next seventy years it built 183,000 apartments in 346 developments — more public housing than the rest of the country's authorities combined.

The data tells a simple story. For thirty-five years everything grew: the towers, the superblocks, the buildings themselves. After 1970, everything reversed.

{{< photos >}}
  {{< photo key="South BK 4:6:26/Edited/JPEGs/IMG_2429-3.jpg" caption="NYCHA towers against the Midtown skyline, Brooklyn." >}}
{{< /photos >}}

{{< chart id="fig-waves" title="Apartments completed per half-decade" sub="Two waves: a New Deal ramp-up, then the great postwar boom. Nearly two-thirds of everything NYCHA ever built opened between 1945 and 1965." h="360" >}}

{{< chart id="fig-stories" title="The tower rose, then fell" sub="Each dot is one new-construction development (n = 235) — hover for its name. Lines are least-squares fits, before and after 1970; bands are 95% confidence intervals." h="430" model="true" >}}

{{< photos >}}
  {{< photo key="South BK 4:6:26/Edited/JPEGs/IMG_2497.jpg" caption="Tower-in-the-park blocks on the horizon, Brooklyn." >}}
  {{< photo key="South BK 4:6:26/Edited/JPEGs/IMG_2506.jpg" caption="Marlboro Houses, Gravesend — six stories, cherry trees." >}}
{{< /photos >}}

{{< chart id="fig-footprint" title="The shrinking superblock" sub="Average land per development, and the slice of it covered by buildings. The 18-acre tower-in-the-park site of the 1950s gave way to infill under 2 acres." h="380" >}}

{{< chart id="fig-scale" title="Apartments per building" sub="Buildings themselves scaled up into the late 1960s, then shrank to walk-up size. Eras after 2000 average a single development each." h="340" >}}

{{< chart id="fig-cost" title="Construction cost per rental room" sub="Average development cost per rental room, in nominal dollars — a 30× climb from First Houses to the last conventional builds." h="360" >}}

{{< photos >}}
  {{< photo key="BK + Broad Channel Feb '26/Edited/IMG_0903.jpg" caption="Eleanor Roosevelt Houses, Brooklyn." >}}
  {{< photo key="Hells Kitchen + LES 3:31:26/Edited/IMG_2144.jpg" caption="Robert S. Fulton Houses, Chelsea." >}}
{{< /photos >}}
