# Auto-scan extension (MVP)

Added 2026-11-05. **Needs design approval.** The [year-long design](superpowers/specs/2026-10-05-sentinel-year-long-design.md) says the extension "keeps explicit user initiation", and lists continuous scraping as out of scope. Auto-scan relaxes the first rule within the limits below. Record the team's or supervisor's approval of this change before demonstrating it as part of the project.

## What it does

- In the toolbar popup, **Auto-scan this site** turns scanning on for the current site only. Chrome asks for access to that one site. Turning it off stops the scanner and gives the access back. Sites can also be removed in Chrome's extension settings.
- On enabled sites, `extension/scanner.js` reads visible text blocks and links as they scroll into view, and watches the page for new content such as incoming chat messages.
- It never reads form fields, editable text, or hidden content.
- Text is sent in batches through the background worker to `POST /api/scan` on `127.0.0.1:8787`, and to nowhere else.
- Risky items get a red (high) or amber (review) marker and outline in an overlay. Clicking a marker shows the evidence and a suggested action. The page's own content isn't changed. The toolbar badge counts the markers on the current tab.
- If Sentinel isn't running, the scanner waits and retries. It never shows anything as safe.

## `/api/scan`

`{"items": [{"id", "text", "url"?, "link_text"?}]}`. It accepts at most 40 items, and each text can be up to 4,000 characters. It runs the same evidence rules as `/api/analyze`, plus a check for link text that names a different site than the link opens. Results are never stored, and optional learned models aren't run.

How the severity is set:

| Severity | When |
|---|---|
| high | The rules rate the item `high`, or the link text doesn't match the link and there is at least one other indicator. |
| review | The link text doesn't match the link, an abuse phrase appears, or there are at least two fraud indicators. |
| none | A single weak indicator, such as one urgent word, isn't marked. It's too common on ordinary pages. |

## Demo

1. Run `./start-sentinel.sh` on macOS or `start-sentinel.cmd` on Windows.
2. In `chrome://extensions`, turn on Developer mode and load the `extension` folder unpacked. If an older copy was loaded before, reload it.
3. Open `http://127.0.0.1:8787/demo`.
4. In the Sentinel popup, turn on **Auto-scan this site**.
5. Check the markers. Expect these:
   - The job-fee message and the bank-alert message (link text doesn't match) are high.
   - The abusive message is review. The one-time-password request is review with rules only, and high when the learned text model is on (it also flags it).
   - The study-group, library, lunch and picnic messages have no marker.
6. Press **Simulate incoming message**. New messages are scanned as they arrive.
7. Stop the server and reload the page. No markers appear and there are no errors.
8. Turn auto-scan off. The markers disappear.

Mark each step pass or fail, as in the [extension smoke test](extension-smoke-test.md).

## Reading text in images (OCR)

Added 2026-11-06. Page text alone misses scams sent as pictures: forwarded "screenshots", posters and QR codes. A second popup switch, **Read text in images**, adds them.

- It's off by default and applies only to sites where auto-scan is on.
- Chrome lets an extension take a screenshot of a tab only if it has access to all sites, or right after the user clicks it. So turning the switch on asks Chrome for access to all sites (`<all_urls>`, an optional permission). Turning it off gives that access back. If the access is removed in Chrome's settings, the switch turns off.
- `scanner.js` queues images, canvases and inline SVGs that are at least 120 × 40 pixels and mostly on screen. Up to four at a time, it hides its own markers. The background worker then takes a screenshot of the visible tab (`chrome.tabs.captureVisibleTab`), at most about one a second.
- The background worker takes a screenshot only for the top frame of a site where auto-scan is on, and only while that tab is the one on screen. A screenshot taken while the user switches tabs is thrown away. Each screenshot can be read once, only by the tab it came from, and expires after 30 seconds.
- A hidden offscreen document (`offscreen.html`) crops the image regions. It reads text with **Tesseract.js** (English, on this computer) and QR codes with **jsQR**. Both are bundled in `extension/vendor/` ([versions and checksums](../extension/vendor/README.md)), and nothing is downloaded while it runs. The screenshot is never saved or sent anywhere.
- Text below 40% OCR confidence, or with fewer than 12 letters or digits, is dropped. A QR web link is checked as the item's link. A UPI payment QR code is described in words ("This QR code starts a UPI payment to …"), so the payment rules can see it.
- The text found goes through the same `POST /api/scan` as page text. The marker's panel says the text was read from an image, may contain reading mistakes, and shows the QR code's link.
- The extension pages' security policy allows `'wasm-unsafe-eval'`, which the OCR engine needs. It still allows only scripts bundled with the extension.

### Demo

After step 4 above, also turn on **Read text in images**. Then scroll through the chat:

| Image | Expected |
|---|---|
| Rohan's forwarded "account alert" image (`/demo-kyc.svg`) | Marker (urgency, fee and one-time password) |
| Finance Club's poster with a QR code (`/demo-refund.svg`) | High: asks for login details, and the QR code opens an IP address |
| Dev's chat screenshot drawn on a `<canvas>` | Marker (gift cards, payment and urgency) |
| Priya's library poster (`/demo-library.svg`) | No marker |

### Chrome test record — 2026-11-06

Google Chrome on macOS (arm64), with a throwaway profile driven through the DevTools protocol. The demo page was served on port 8788 and checked against the running app on 8787 (with the text model). **Chrome's prompt for all-sites access was not shown.** The test copy of the extension listed `<all_urls>` as a required permission instead, and the switch was set the way the popup sets it.

| Step | Result |
|---|---|
| The first run failed: Chrome blocked the OCR engine's WebAssembly, and Tesseract.js waited forever. Fixed by allowing `'wasm-unsafe-eval'` and adding time limits (45 s start, 20 s per image, 90 s per job). | Fixed |
| Offscreen document starts the OCR engine; test phrase read in 1.2 s at 96% confidence | Pass |
| Badge with page text only: 3. After image reading: 7 (account alert, QR poster and canvas chat marked; library poster not) | Pass |
| Image reading took 1.3–2.5 s for each screenshot of one or two images | Pass |
| QR code decoded to `http://203.0.113.50/refund` and shown in the panel ([screenshot](images/autoscan-ocr-chrome.png)) | Pass |
| Image reading turned off: no further screenshots | Pass |
| Page errors | None |

Still to check by hand: the popup switch with Chrome's real permission prompt, and whether turning it off (removing `<all_urls>`) leaves the access for each auto-scan site in place.

## Limits and next steps

- With `start-sentinel.sh` and the text-ml artifact present, markers combine the rules with the experimental [learned scam-text model](text-ml-workflow.md). Without it, markers come from rules only.
- OCR reads English only, and stylised fonts, low-contrast text and small text may be misread. The QR pattern itself produces some junk characters, which the rules ignore. Videos and CSS background images aren't read. A canvas is read once, even if it is redrawn later.
- Next phase: adapters for specific sites, to turn chats into ordered conversation turns for the context-harm check.

## Chrome test record — 2026-11-05

Google Chrome 156.0.8078.80 on macOS (arm64), with a throwaway profile. The unpacked `extension` folder was loaded through the DevTools protocol, and the pages were driven the same way. The demo server ran through `start-sentinel.sh`. Auto-scan was turned on by calling the same background function the popup switch calls. **Chrome's permission prompt for the switch itself was not exercised.** Only the Sentinel app's own address was used, and the extension already has permission for it.

| Step | Result |
|---|---|
| Extension loads; service worker starts | Pass |
| Turn on for the demo site: content script registered for `http://127.0.0.1:8787/*` | Pass |
| Markers on the demo page: 2 high, 2 review, no marker on benign messages; badge `4` | Pass |
| Three simulated incoming messages: two new high markers, none on the benign one; badge `6` | Pass |
| Clicking a marker opens the evidence panel with the link-mismatch evidence | Pass ([screenshot](images/autoscan-chrome.png)) |
| Page reload: the registered script injects itself again; badge `4` | Pass |
| Server stopped, then reload: no markers, badge empty, no page errors | Pass |
| Server restarted, then reload: markers return | Pass |
| Popup renders the switch; it is disabled on non-web pages | Pass |
| Turn off: overlay removed, badge cleared, registration removed | Pass |

Still to check by hand: clicking the popup switch on a real website, including Chrome's site-access prompt, and the existing explicit-check [smoke test](extension-smoke-test.md).

## Auto-scan every website (added 2026-11-06)
The popup's **Auto-scan every website** switch checks visible text on every http(s) page automatically, so no text has to be selected. Chrome asks once for access to all sites, and turning the switch off gives that access back. Sites that were turned on individually keep scanning. As before, page text goes only to Sentinel on this computer and nothing is saved.

Harmful-language rules now also flag **threats of harm** as high, for example "you will die", "your days are numbered", "I will make you pay", "…or else you will die", "tu mar jayega" and "tujhe dekh lunga". Coercive demands such as "give me my money back or else" are flagged for review.

**Busy pages (2026-11-06).** Pages that change all the time (Gmail, chat apps, live feeds) never went quiet for the scanner's 800 ms pause, so new content such as an opened email was never scanned. Rescans now happen at least every 1.5 s, only the changed parts of the page are re-read, and choosing text blocks no longer compares every block with every other, which kept large pages slow. The toolbar count also goes down when a flagged message is removed or edited.

**Gmail and nested layouts (2026-11-06).** Text is now grouped by its *nearest* block element (anything not displayed inline). Previously it was grouped by a known block that could be far up the page. In Gmail the email body belonged to the whole `role="listitem"` message, and that was then discarded as a container of the header cells, so the body was never scanned. Short messages of at least two words and eight characters ("you will die") are now scanned too. Single words, such as menu labels, are still skipped.

**After reloading or updating the extension (2026-11-06).** Chrome cuts already-open tabs off from a reloaded extension, and the old scanner then threw "Cannot read properties of undefined (reading 'sendMessage')". It now notices this and shuts down cleanly, and the background worker injects the new scanner into open tabs on auto-scan sites, so those pages keep being checked without being reloaded.

**False positives on email (2026-11-06).** In Gmail, ordinary notices from banks, AWS, Google, Vercel and OpenAI were being marked. Two causes, both fixed:
- **The text model.** It was trained on SMS and rates polite corporate wording as phishing, scoring 0.67–0.96 on these emails against 0.98–1.00 for real phishing. While scanning, its score now counts only when something independent backs it up: a link, a rule hit or a link-text mismatch. The report still shows the score, with `counted: false` and the reason.
- **The rules.** They matched *mentions* ("UPI", "payment", "OTP"), so a bank alert reporting a UPI debit was read as "asks for payment". They now match *requests* ("pay the fee", "send money", "enter your card details", "share your OTP") and ignore negated advice ("never share your OTP"). A prize or lottery rule was added. The old mention patterns are kept unchanged for the paired and bot models, which were trained on them.

Check after the fix: 12 legitimate inbox texts got no marker; 9 scams and threats were still marked (8 high, 1 review).
