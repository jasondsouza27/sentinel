# Sentinel: project assessment and screen-reading roadmap

Written 2026-11-06 on macOS. It is based on the current files in this folder and a fresh test run. The [README](../README.md) status table and the [viva guide](viva-guide.md) give the full detail. This page answers two questions: what is done, partial or missing, and what to do next for the demo site and the screen-reading extension.

## Fresh verification

| Suite | Result (2026-11-06) |
|---|---|
| App, models, bot detection, network, harm rules (`.venv-text-ml`, 9 modules) | **112 / 112 pass** (10 s) |
| Web app and extension JavaScript (`node --test tests/*.test.mjs`) | **68 / 68 pass** |
| Full research suite (`.venv-ml`, Python 3.11) | Not re-run here. Last record: 518 of 569 pass; the 43 failures are Windows-only `context_harm` tests ([testing.md](testing.md)) |

## Status by area

### Done (live in the app)

| Area | Notes |
|---|---|
| Demo web app, 4 pages | `/` content checks, `/bot` bot accounts, `/network` community network, `/demo` auto-scan demo page. One shared API in `sentinel/server.py`. |
| Fraud and link rules | Payment, credential and urgency wording; URL structure; link-text mismatch in `/api/scan`. |
| Harmful-language rules | 26 rules, 11 categories, English and Hinglish (`sentinel/harm_rules.py`). |
| Learned scam-text model `text-ml-v2` | DistilBERT + TF-IDF, calibrated, word-level explanations. Live but experimental: its added training data is synthetic. |
| Bot account detection | 25-signal heuristic over YouTube/Reddit APIs or uploaded data; `bot-ml-activity-v1` live for X accounts with ≥ 20 posts. |
| Community scam network | MinHash fingerprints, k-anonymous hub, 10,000-user simulation. Loopback prototype. |
| Conversation investigation | Ordered turns, target selection, signed saving, reopen, feedback, export, delete. |
| Chrome extension (MV3, v0.2.0) | Popup and context-menu checks, plus opt-in **auto-scan** of visible page text (below). |

### Partial

| Area | What's missing |
|---|---|
| Auto-scan extension | Reads **DOM text only**. No reading of text inside images, canvas or video. No site adapters (chats aren't turned into ordered conversations). Chrome's site-access prompt from the real popup switch, and the older explicit-check [smoke test](extension-smoke-test.md), haven't been checked by hand. |
| Auto-scan design approval | The [year-long design](superpowers/specs/2026-10-05-sentinel-year-long-design.md) says the extension "keeps explicit user initiation". Auto-scan relaxes that. The supervisor's approval isn't recorded yet ([autoscan-extension.md](autoscan-extension.md)). |
| `text-ml-v2` | Not validated on real, consented messages (for example Indian SMS). |
| Bot ML | Profile model `bot-ml-v1` failed its release gate and is withheld. Needs more varied data (for example TwiBot-22). |
| Community network | Runs on loopback only. No real multi-user deployment or pairing. |

### Missing or blocked

| Area | Blocker |
|---|---|
| Paired message + link study (the central research question) | `data/curation/intake.csv` is empty. 100 phishing and 18 possible legitimate candidates are unreviewed. Needs verified legitimate pairs and two-reviewer labelling. |
| Learned harm model | Real CAD allocation fails three support gates (175 positive training cases, minimum 200). Needs a new data/protocol version. |
| Learned URL warnings | URL-v3 false-positive rates (5.76% primary, 22.39% supplemental) block live use. |
| Team workflows | Year-long design phase E: authenticated team demo, scoped pairing token for the extension, shared case review. Not started. |
| Usability pilot | 15–20 person pilot not prepared or run. |
| Final report | `docs/report/main.tex` exists; final results, limitations and pilot record are still to come. |

## Screen-reading extension: options

The goal is an extension that automatically reads or "sees" what's on screen and sends it to Sentinel's detection. DOM reading is already built. These are the remaining ways to widen it.

| Approach | What it catches | Cost and risk | Recommendation |
|---|---|---|---|
| Content script DOM reading + `IntersectionObserver` + `MutationObserver` | Visible text, links, new chat messages | Already built in `extension/scanner.js`. Per-site opt-in. | **Keep.** It's the base. |
| `chrome.tabs.captureVisibleTab` + on-device OCR (Tesseract.js in an offscreen document) | Text inside images, memes, screenshots of chats, canvas apps | Only the visible tab, needs `<all_urls>` or `activeTab`. OCR is slow (~1–3 s per frame on CPU) and makes mistakes. Screenshots are sensitive, so they must never leave the machine. Rate limit captures (Chrome caps it at about 2 per second). | **Next phase.** Run OCR only on regions the DOM can't explain (`img`, `canvas`, `video` poster frames), at most every few seconds, and only on opted-in sites. |
| OCR on the server (Python, e.g. Tesseract or EasyOCR) | Same as above, better accuracy | Sends screenshots to the local server. Still local, but larger payloads and a new dependency. | Fallback if browser OCR is too slow. Keep it on `127.0.0.1` only. |
| Image classifier for scam/abuse images | Fake-payment screenshots, QR codes, explicit images | New model and data work; release gate needed. | Later. Start with QR decoding (jsQR), which sends the decoded URL to the existing link rules. |
| Site adapters (WhatsApp Web, Instagram DMs, Telegram Web, Gmail) | Turns chats into ordered sender-labelled turns for the conversation check | Pages change often; adapters break. | After OCR. Start with one site used in the demo. |
| `chrome.desktopCapture` / whole-screen capture | Other apps outside the browser | Heavy permission, a picker every time, poor fit for a browser extension. | **Don't.** Out of scope. |

Privacy rules to keep for every phase: off by default and turned on per site; nothing goes anywhere except `127.0.0.1:8787`; no form fields, editable text or password fields; nothing stored unless the user presses **Save case**; never mark anything as "safe".

## Roadmap

Effort is in focused working days for one person.

| # | Task | Effort | Why now |
|---|---|---|---|
| 1 | Record supervisor approval for auto-scan, or limit the demo to explicit checks | 0.5 | It blocks presenting the main new feature. |
| 2 | Put this macOS folder under version control (its own repo, or sync with the teammate's private GitHub repo). The Git root here is the whole home folder with no commits. | 0.5 | Nothing done on this Mac since 2026-11-05 is in version control. |
| 3 | Hand-run the two extension checklists in real Chrome: popup switch with the site-access prompt, and the explicit-check smoke test | 1 | Last unchecked extension steps. |
| 4 | ~~OCR phase: `captureVisibleTab` → offscreen document → Tesseract.js → `/api/scan`; markers drawn over image regions; QR decoding~~ | **Done 2026-11-06** | See [autoscan-extension.md](autoscan-extension.md#reading-text-in-images-ocr). Chrome's real permission prompt is still to be checked by hand. |
| 5 | ~~Add image items to `/demo` and tests for them~~ | **Done 2026-11-06** | The demo has an alert image, a QR poster, a canvas chat screenshot and a harmless poster. |
| 6 | One site adapter producing ordered conversation turns | 4–6 | Connects auto-scan to the conversation/context check. |
| 7 | Validate `text-ml-v2` on real consented messages | 3–5 + data collection | The live model is trained partly on synthetic data. |
| 8 | Paired-study data: admit verified legitimate pairs, two-reviewer labelling, freeze test set | Several weeks, team | The central research question; currently empty. |
| 9 | Retrain bot profile model with varied data (TwiBot-22) and re-gate | 4–6 | Profile model is withheld. |
| 10 | Team workflow: authentication, extension pairing token, shared review | 8–12 | Year-long phase E. |
| 11 | Usability pilot (15–20 people) and final report | 2–3 weeks | Year-long phase F. |

## Risks

- **No version control on this Mac copy.** See roadmap item 2.
- **Platforms.** Lock files are Windows/Python 3.11. This Mac runs Python 3.14 by default; the app uses `.venv-text-ml` and research uses `.venv-ml` (3.11). The 43 `context_harm` tests only pass on Windows.
- **Design drift.** Auto-scan, the community network and bot detection go beyond the approved year-long design. Each needs a recorded scope decision.
- **Synthetic training data** in `text-ml-v2` and the bot models. Claims must stay "experimental" until real-data validation is done.
- **OCR performance.** Tesseract.js on a laptop CPU may be too slow for continuous capture. Measure before promising "real-time".
- **Chrome Web Store.** Broad optional host permissions plus screenshots would need a strong privacy policy if the extension is ever published. For the project, unpacked loading is enough.
