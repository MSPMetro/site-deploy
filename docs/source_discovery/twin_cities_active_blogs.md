# Twin Cities active blogs (discovered)

These were discovered via `scripts/discover_sources.py` using DuckDuckGo seed searches for:
“Twin Cities”, “Twin Cities Metropolitan Area”, “Minneapolis”, “Saint Paul”.

Criteria used here:
- Has a working RSS/Atom feed
- Recent publishing activity (generally ≤ 30 days)
- Not on the explicit paywalled denylist
- Excludes comment feeds

## Candidates (RSS/Atom)

- Racket — https://racketmn.com/ — feed: https://racketmn.com/feed
- urbanMSP — https://urbanmsp.com/ — feed: https://urbanmsp.com/feed
- St. Paul Voice / St Paul Publishing — https://www.stpaulpublishing.com/ — feed: https://www.stpaulpublishing.com/rss.xml
- Community Reporter — https://communityreporter.org/ — feed: https://communityreporter.org/feed/
- Minnesota Monthly — https://www.minnesotamonthly.com/ — feed: https://www.minnesotamonthly.com/feed/
- Artful Living — https://artfulliving.com/ — feed: https://artfulliving.com/feed/
- The Minnesota Daily — https://mndaily.com/ — feed: https://mndaily.com/feed/
- Midwest Design — https://midwestdesignmag.com/ — feed: https://midwestdesignmag.com/feed/
- Twin Cities Family — https://twincitiesfamily.com/ — feed: https://twincitiesfamily.com/feed/
- Twin Cities Frugal Mom — https://twincitiesfrugalmom.com/ — feed: https://twincitiesfrugalmom.com/feed/
- PhenoMNal Twin Cities — https://www.phenomnaltwincities.com/ — feed: https://www.phenomnaltwincities.com/feed/
- Secret Minneapolis — https://secretminneapolis.com/ — feed: https://secretminneapolis.com/feed

## Notes

- Some sites discovered during search did not expose RSS/Atom feeds (may require allowlisted HTML scraping later).
- A few large outlets were excluded due to paywall/metering (see `docs/source_discovery/denylist_paywalled_domains.txt`).
