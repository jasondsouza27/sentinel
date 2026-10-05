# Chrome extension smoke test

Run this once in a real Chrome browser before demonstrating Sentinel. Record the browser version and test date in your project log. Use invented `.example` text and links for these checks; do not submit private messages just to test the UI.

1. Start Sentinel with `start-sentinel.cmd` and confirm `http://127.0.0.1:8787/api/health` shows `"status": "ok"`.
2. In `chrome://extensions`, enable Developer mode and load the project's `extension` folder unpacked. Confirm the Sentinel toolbar button appears.
3. On Sentinel's own web page, select the heading `Pause before you trust the link.` Click the toolbar button, choose **Use selected text**, then **Check with Sentinel**. Confirm the selected text appears and an assessment is shown.
4. Right-click selected text and choose **Check selected text with Sentinel**. Confirm the popup is filled, or that the text is waiting when the toolbar button is opened.
5. Right-click the page's **Start a check** link and choose **Check link with Sentinel**. Confirm the URL field is filled. Add the invented message `Please visit this page` and check that both inputs are submitted together.
6. Check the full web app's case history. The above analyses should not appear there until **Save case locally** is clicked. Save one synthetic case, confirm it appears, then delete it.
7. Stop the local server and try a check. The extension should explain that Sentinel must be started, without showing a false safety verdict.

Mark each step pass/fail and save any error text in the project log. The automated tests verify the extension-origin API request and server behavior, but they cannot substitute for the toolbar and context-menu check in Chrome.
