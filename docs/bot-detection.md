# Social media bot account detection

**Page:** `http://127.0.0.1:8787/bot`. **API:** `GET /api/bot/platforms` and `POST /api/bot/analyze`.

The module estimates whether an account behaves like a person, an automated bot, or part of a coordinated campaign. It's separate from the existing **Profile indicators** check in `/api/analyze`, which is unchanged.

## Data sources (no scraping)

| Platform | Official API | Other sources |
|---|---|---|
| YouTube | YouTube Data API v3: set `YOUTUBE_API_KEY` | Upload, manual |
| Reddit | Reddit OAuth (application-only): set `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | Upload, manual |
| X (Twitter) | Not used (paid API) | Upload, manual |
| Instagram, Facebook | Not used (Graph APIs only cover accounts you manage) | Upload, manual |

- **Profile URLs are never fetched.** They're only parsed against an exact host allowlist to get the username, so a submitted URL can't make the server contact anything (no SSRF).
- **API calls are restricted.** They go only to `www.googleapis.com`, `www.reddit.com` and `oauth.reddit.com`, over HTTPS. Redirects aren't followed, requests have a 10-second timeout, and responses are capped at 2 MB. API keys come only from environment variables and never appear in errors or logs.
- **Data the user supplies** is either an upload (JSON or CSV, up to 3,000 posts and 3 MB) or profile facts entered by hand.
  - CSV columns: `timestamp,text,is_repost,likes,replies,shares`. Only `timestamp` is required, as ISO-8601 or Unix seconds.
  - JSON: `{"profile": {...}, "posts": [...]}`. See `sentinel/bot_detection/adapters/supplied.py`.
- **Nothing is stored.** Logs record only the platform, data source, number of posts and outcome, never usernames or content. Analyses are limited to 12 per minute.

## How scoring works

1. **Features** (`features.py`). These cover the profile (age, completeness, picture, username pattern, bio, verified), activity (rate, interval regularity, repeated intervals, a rest period, bursts, sudden change, reposts), content (exact and near duplicates using the community network's MinHash, hashtags, links, single-domain links, vocabulary diversity, spam language) and engagement (following/followers ratio, engagement rate and uniformity, follower jumps). Each feature is `None` when its data is missing.
2. **Signals** (`weights.json`, editable without code changes). Each of the 25 signals turns one feature into a 0–1 suspicion level, with a weight and an explanation. Timing signals need a minimum number of posts.
3. **Score** = 100 × Σ(weight × suspicion) ÷ Σ(weight), over **available signals only**. It's a heuristic bot-likeness index, **not a probability**.
4. **Confidence** depends on signal coverage and the number of posts, never on the score:
   - **High:** at least 65% coverage and 50 posts.
   - **Medium:** at least 40% coverage and 20 posts.
   - **Very low** below 25% coverage or 4 signals. In that case the classification is "Insufficient data" and the headline score is withheld.
5. **Classification:**
   - Below 30: likely human-operated.
   - 60 or above: likely bot or automated.
   - 40–59 with coordination signals at 60 or above: possibly coordinated.
   - Otherwise: suspicious, mixed patterns.

   Risk level: Low (below 30), Moderate (below 55), High (below 75), Very high.

`HeuristicScorer.score(features, posts)` is the replaceable interface. A trained model can implement the same method and be passed to `BotDetectionService(scorer=...)`.

## Known examples
`tests/fixtures/bot_accounts.json` holds three invented accounts:

| Account | Score | Classification | Confidence |
|---|---|---|---|
| Scheduled spam bot | 86 | Likely automated (coordination flag on) | High |
| Ordinary student | 4 | Likely human | High |
| Human-paced coordinated account | 46 | Possibly coordinated | High |

These test that the logic behaves as intended. **They aren't an accuracy evaluation**, because the weights were set by hand.

## Limits and next steps
- The weights are set by hand, not learned or calibrated. The next step is a trained, replaceable model evaluated on a public bot dataset. The project design names TwiBot-22 as a candidate; its licence and feature availability need auditing first. Only features that can actually be obtained at analysis time would be used.
- **Uploaded data can't be verified.** A curated or partial export can make an account look more or less bot-like.
- **Coordination is assessed from a single account.** True network detection needs several accounts, for example comparing post fingerprints across accounts.
- Hour-of-day charts use UTC, so an account's apparent rest period shifts with its time zone.
