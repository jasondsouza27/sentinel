"""Explainable harmful and dangerous language detection (English and Hinglish).

Rules are grouped into categories with a severity:
  high   - threats of violence, mass-violence threats, telling someone to self-harm,
           sextortion/blackmail, doxxing/stalking threats, dehumanising hate,
           and self-harm risk (handled with a supportive action, not a report)
  review - directed insults and harassment
  low    - profanity on its own (noted, not flagged)

Text is normalised first (leetspeak, look-alike letters, stretched letters,
dotted spelling) so simple disguises still match. Context lowers certainty:
quoted or reported speech and negations ("I would never hurt you") become
review items, and common idioms ("you killed it", "killer performance") are
excluded. Rules flag observable wording; they cannot judge intent.
"""

import re
import unicodedata

LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})
CONFUSABLE = str.maketrans({"а": "a", "е": "e", "о": "o", "с": "c", "р": "p", "х": "x", "і": "i", "ѕ": "s"})

YOU = r"(?:you|u|ya|yu|your\s+(?:family|kids?|mom|mother|dad|father|sister|brother|wife|husband))"
PERSON = rf"(?:{YOU}|him|her|them|everyone|everybody|all\s+of\s+you)"
VIOLENT = r"(?:kill|murder|stab|shoot|strangle|choke|beat\s+(?:up)?|hurt|smash|break\s+your|slit|burn|rape|attack|end)"
FUTURE = r"(?:i\s*(?:will|'ll|ll|am\s+going\s+to|'m\s+going\s+to|m\s+going\s+to|am\s+gonna|'m\s+gonna|m\s+gonna|gonna|want\s+to|wanna)|we\s*(?:will|'ll|are\s+going\s+to|re\s+gonna))"

# (category, severity, pattern, description)
RULES = [
    ("threat_violence", "high", rf"\b{FUTURE}\s+(?:\w+\s+){{0,2}}{VIOLENT}\w*\s+{PERSON}\b",
     "A direct threat of violence against a person."),
    ("threat_violence", "high", rf"\b(?:{YOU})\s*(?:are|r|'re|re)\s+(?:so\s+)?(?:dead|going\s+to\s+die|gonna\s+die)\b",
     "Tells someone they are dead or going to die."),
    ("threat_violence", "high", r"\b(?:watch\s+your\s+back|you(?:'ll|\s+will)\s+(?:regret|pay\s+for)\s+(?:this|it)|sleep\s+with\s+one\s+eye\s+open)\b",
     "Intimidating language that implies a threat."),
    ("threat_violence", "high", r"\b(?:main\s+)?(?:tu(?:j|jh)he|tumhe|tujhko|tereko|use|usko)\s+(?:jaan\s+se\s+)?(?:maar|mar|kaat|kat|pel)\s*(?:dunga|dungi|denge|daalunga|dalunga|dalungi|daalenge|doonga)\b",
     "A threat of violence (Hinglish)."),
    ("threat_violence", "high", r"\b(?:jaan\s+se\s+maar|khatam\s+kar\s+(?:dunga|dungi|denge))\b",
     "A threat to kill (Hinglish)."),
    ("mass_violence", "high", r"\b(?:bomb|blow\s+up|shoot\s+up|set\s+fire\s+to|burn\s+down|attack)\s+(?:the|this|that|our|your|a)?\s*(?:school|college|class|campus|office|mall|temple|mosque|church|station|airport|hospital|building|hostel|metro)\b",
     "A threat of violence against a place or group of people."),
    ("mass_violence", "high", r"\b(?:i(?:'m|\s+am)?\s*(?:going\s+to|gonna|will)\s+(?:bring\s+a\s+gun|plant\s+a\s+bomb)|mass\s+shooting|school\s+shooting)\b",
     "References planning a mass-violence attack."),
    ("self_harm_encouragement", "high", r"\b(?:kill\s+your\s*self|kys|go\s+die|go\s+and\s+die|drink\s+bleach|hang\s+your\s*self|end\s+your\s+(?:life|self)|you\s+should\s+(?:die|kill\s+your\s*self|not\s+exist)|nobody\s+would\s+miss\s+you|world\s+(?:is|would\s+be)\s+better\s+without\s+you|mar\s+ja(?:a|o)?|marja)\b",
     "Encourages someone to harm or kill themselves."),
    ("self_harm_risk", "high", r"\b(?:i\s*(?:want|wanna|am\s+going|'m\s+going|m\s+going|plan|am\s+planning)\s+to\s+(?:die|kill\s+my\s*self|end\s+(?:my\s+life|it\s+all|everything)|hurt\s+my\s*self|cut\s+my\s*self)|kill\s+my\s*self|end\s+my\s+life|suicid(?:e|al)|no\s+reason\s+to\s+live|better\s+off\s+dead|don'?t\s+want\s+to\s+(?:live|be\s+alive)|cut(?:ting)?\s+my\s*self|main\s+mar\s+jaunga|mujhe\s+marna\s+hai|jeena\s+nahi\s+chahta)\b",
     "Possible risk of self-harm or suicide."),
    ("sextortion", "high", r"\b(?:send\s+(?:me\s+)?(?:nudes|nude\s+pics|naked\s+(?:pics|photos))|(?:leak|post|share|send|upload|viral\s+kar)\w*\s+(?:your|ur|teri|tumhari)\s+(?:nudes?|photos?|pics?|pictures|videos?|chats?|private\s+\w+))\b",
     "Sexual coercion or a threat to expose private images."),
    ("blackmail", "high", r"\b(?:or\s+(?:else\s+)?i(?:'ll|\s+will)\s+(?:tell|leak|post|share|expose|send)|pay\s+(?:me\s+)?or\s+i(?:'ll|\s+will)|i\s+have\s+your\s+(?:photos|pics|videos|chats|secrets))\b",
     "Blackmail or coercion."),
    ("doxxing_stalking", "high", r"\b(?:i\s+know\s+where\s+you\s+(?:live|stay|study|work)|i(?:'ll|\s+will)\s+(?:find|come\s+to)\s+(?:you|your\s+house)|i(?:'m|\s+am)\s+outside\s+your\s+(?:house|home|room|hostel)|(?:here\s+is|this\s+is)\s+(?:his|her|their|your)\s+(?:home\s+)?address)\b",
     "Stalking or exposing someone's location."),
    ("hate_dehumanising", "high", r"\b(?:all\s+)?(?:muslims|hindus|christians|sikhs|jews|dalits|blacks|black\s+people|women|gays|lesbians|trans\s+people|immigrants|refugees|biharis|northeasterners|kashmiris)\s+(?:are|r)\s+(?:animals|vermin|cockroaches|rats|dogs|parasites|subhuman|filth|a\s+disease)\b",
     "Dehumanising language about a group of people."),
    ("hate_dehumanising", "high", r"\b(?:kill|exterminate|wipe\s+out|get\s+rid\s+of)\s+all\s+(?:the\s+)?(?:muslims|hindus|christians|sikhs|jews|dalits|blacks|women|gays|immigrants|refugees)\b",
     "Calls for violence against a group of people."),
    ("harassment", "review", rf"\b(?:{YOU})\s*(?:are|r|'re|re)\s+(?:such\s+an?\s+|so\s+|an?\s+|the\s+|a\s+total\s+|a\s+complete\s+)?(?:\w+\s+)?(?:stupid|idiot|moron|dumb|retard\w*|loser|worthless|useless|pathetic|ugly|fat|disgusting|trash|garbage|waste|freak|failure|joke|clown|nobody|nothing|bitch|slut|whore|bastard|scum)\b",
     "A directed insult."),
    ("harassment", "review", r"\b(?:shut\s+up|nobody\s+(?:likes|wants|cares\s+about)\s+you|everyone\s+hates\s+you|no\s+one\s+(?:likes|wants)\s+you|get\s+lost|you\s+don'?t\s+belong|stupid\s+idiot|ugly\s+fat|fat\s+loser|dumb\s+\w+)\b",
     "Harassing or demeaning language."),
    # Strong slurs are abusive on their own; milder words ("kutta" = dog, "pagal" = crazy) count only
    # when aimed at someone ("tu", "tum", "abe"...).
    ("harassment", "review", r"\b(?:chutiya|chu\s*tiya|harami|bhosdi\w*|madarchod|behenchod|bhenchod|randi|kamina|kamine)\b",
     "An abusive term (Hinglish)."),
    ("harassment", "review", r"\b(?:tu|tum|tujhe|tumhe|tera|teri|abe|oye|you|u)\b(?:\s+\w+){0,3}?\s+(?:pagal|bewakoof|bevkoof|gadha|gadhe|ullu(?:\s+ka\s+pattha)?|nalayak|kutte|kutta|kutiya|saala|saali)\b|\b(?:pagal|bewakoof|bevkoof|gadha|gadhe|nalayak|kutte|kutta|kutiya|saala|saali)\s+(?:hai\s+)?(?:tu|tum|kahin\s+ka)\b",
     "An insult aimed at someone (Hinglish)."),
    ("profanity", "low", r"\b(?:fuck\w*|shit\w*|bitch\w*|asshole|damn|crap|wtf|stfu)\b",
     "Profanity (not harmful on its own)."),
]
COMPILED = [(c, s, re.compile(p, re.IGNORECASE), d) for c, s, p, d in RULES]

NEGATION = re.compile(r"\b(?:never|not|wouldn'?t|won'?t|don'?t|didn'?t|nobody\s+should|no\s+one\s+should|would\s+never)\b[^.!?]{0,25}$", re.IGNORECASE)
REPORTED = re.compile(r"[\"“”‘’]|\b(?:reported|quoted|someone\s+(?:wrote|said|told|sent)|he\s+said|she\s+said|they\s+said|told\s+me|messaged\s+me|sent\s+me|received|screenshot|said\s+that)\b", re.IGNORECASE)
IDIOM = re.compile(r"\b(?:killed\s+it|killing\s+it|killer\s+(?:performance|app|look|feature|deal)|dying\s+of\s+laughter|i'?m\s+dead\b(?!\s+serious)|kill\s+(?:the\s+)?(?:process|task|switch|time|bill)|shoot\s+(?:me\s+)?(?:a\s+)?(?:message|mail|email|text)|break\s+a\s+leg)\b", re.IGNORECASE)

SEVERITY_ORDER = {"low": 0, "review": 1, "high": 2}
ACTIONS = {
    "self_harm_risk": ("If you or someone you know may be at risk, reach out now: in India call Tele-MANAS 14416 "
                       "(free, 24x7) or emergency services 112. Stay with the person and remove means of harm."),
    "threat_violence": "Do not engage. Save the evidence (screenshots with dates) and report it to the platform and, if you feel unsafe, to police (112).",
    "mass_violence": "Treat this seriously: save the evidence and report it immediately to the police (112) and the institution.",
    "self_harm_encouragement": "Do not engage. Save the evidence, block the sender and report it to the platform.",
    "sextortion": "Do not pay or send anything. Save the evidence, block the sender and report it at cybercrime.gov.in or 1930.",
    "blackmail": "Do not pay or comply. Save the evidence and report it at cybercrime.gov.in or the cyber helpline 1930.",
    "doxxing_stalking": "Save the evidence, tighten your privacy settings and report it to the platform; contact police (112) if you feel unsafe.",
    "hate_dehumanising": "Save the evidence and report it to the platform; do not amplify it by sharing.",
    "harassment": "Review the surrounding conversation, save evidence and consider blocking or reporting if it continues.",
}


# Most urgent advice first when several categories match.
ACTION_PRIORITY = ["self_harm_risk", "mass_violence", "threat_violence", "sextortion", "blackmail",
                   "self_harm_encouragement", "doxxing_stalking", "hate_dehumanising", "harassment"]


def normalise(text):
    text = unicodedata.normalize("NFKC", text).translate(CONFUSABLE)
    text = re.sub(r"\b(?:[a-z]\s?[.\-*_]\s?){2,}[a-z]\b", lambda m: re.sub(r"[\s.\-*_]", "", m.group(0)), text, flags=re.IGNORECASE)
    # Digits/symbols inside words only (keep real numbers such as 112 or prices).
    text = re.sub(r"\b\w*[a-z][\w@$!]*\b", lambda m: m.group(0).translate(LEET), text, flags=re.IGNORECASE)
    text = re.sub(r"([a-z])\1{2,}", r"\1", text, flags=re.IGNORECASE)  # stuuupid -> stupid
    text = text.replace("’", "'")
    return re.sub(r"\s+", " ", text)


def detect(text):
    """Return {"level", "categories", "matches"} for one text."""
    if not text or not text.strip():
        return {"level": "not_assessed", "categories": [], "matches": []}
    clean = normalise(text)
    idioms = [m.span() for m in IDIOM.finditer(clean)]
    reported = bool(REPORTED.search(text))
    matches = []
    for category, severity, pattern, description in COMPILED:
        for m in pattern.finditer(clean):
            if any(a <= m.start() < b or a < m.end() <= b for a, b in idioms):
                continue
            prefix = clean[max(0, m.start() - 40):m.start()]
            negated = bool(NEGATION.search(prefix)) and category not in ("self_harm_risk",)
            adjusted = severity
            if severity == "high" and (negated or (reported and category != "self_harm_risk")):
                adjusted = "review"
            if negated and severity == "review":
                continue
            matches.append({"category": category, "severity": adjusted, "description": description,
                            "negated": negated, "reported": reported and category != "self_harm_risk"})
            break
    flagged = [m for m in matches if m["severity"] != "low"]
    level = ("high" if any(m["severity"] == "high" for m in matches)
             else "review" if flagged else "low_observed_concern")
    categories = sorted({m["category"] for m in matches}, key=lambda c: -max(
        SEVERITY_ORDER[m["severity"]] for m in matches if m["category"] == c))
    return {"level": level, "categories": categories, "matches": matches}


def assessment(content):
    """The `harmful_content` block of /api/analyze."""
    if not content:
        return {"level": "not_assessed", "categories": [], "evidence": [],
                "uncertainty": "No text was supplied.", "action": "Review the full context before drawing conclusions."}
    found = detect(content)
    evidence = []
    for m in found["matches"]:
        note = m["description"]
        if m["reported"]:
            note += " It appears in quoted or reported context, so human review is needed."
        elif m["negated"]:
            note += " It appears near a negation, so it may not be a real threat; review the context."
        evidence.append(note)
    top = next((c for c in ACTION_PRIORITY if c in found["categories"]), None)
    action = ACTIONS.get(top, "Review the full context before drawing conclusions.")
    return {"level": found["level"], "categories": found["categories"], "evidence": evidence,
            "method": "explainable language rules (English and Hinglish)",
            "uncertainty": ("Rules match wording, not intent: jokes, song lyrics or reclaimed language can be flagged, "
                            "and new slang or other languages can be missed. One message cannot establish a pattern of bullying."),
            "action": action}
