#!/bin/sh
# macOS/Linux launcher: the counterpart of start-sentinel.cmd.
# When the text-model environment and artifact exist, the experimental learned
# scam-text model is turned on; otherwise Sentinel runs with rules only.
cd "$(dirname "$0")" || exit 1
TEXT_PY=".venv-text-ml/bin/python"
TEXT_MODEL="models/text-ml/v2"
[ -f "$TEXT_MODEL/manifest.json" ] || TEXT_MODEL="models/text-ml/v1"
if [ -x "$TEXT_PY" ] && [ -f "$TEXT_MODEL/manifest.json" ] && [ -z "$SENTINEL_RULES_ONLY" ]; then
  echo "Learned scam-text model: on ($TEXT_MODEL). Set SENTINEL_RULES_ONLY=1 to turn it off."
  BOT_ARGS=""
  [ -f models/bot-ml/v1/manifest.json ] && BOT_ARGS="--bot-model models/bot-ml/v1"
  [ -f models/bot-ml/activity-v1/manifest.json ] && BOT_ARGS="$BOT_ARGS --bot-activity-model models/bot-ml/activity-v1"
  exec "$TEXT_PY" -m sentinel.server --text-model "$TEXT_MODEL" $BOT_ARGS "$@"
fi
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    exec "$candidate" -m sentinel.server "$@"
  fi
done
echo "Python 3.10 or newer is required. Install it, then run this file again." >&2
exit 1
