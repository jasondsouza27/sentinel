"""Explainable harmful and dangerous language detection (English and Hinglish).

Rules are grouped into categories with a severity:
  high   - threats of violence, mass-violence threats, telling someone to self-harm,
           sextortion/blackmail, doxxing/stalking threats, dehumanising hate,
           and self-harm risk (handled with a supportive action, not a report)
  review - directed insults, harassment, slurs, strong abusive terms and coercion ("...or else")
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
YOU_ARE = rf"(?:(?:{YOU})\s*(?:are|r|'re|re|is)|ur|youre)"
FUCK = r"f(?:u|a|\*+|v)?c?\*?k+"

# English insults. Nouns can be aimed at someone directly ("you idiot");
# adjectives need "you are" ("you are ugly").
EN_NOUN = (r"(?:idiots?|moron\w*|dumbass\w*|dumb\s+ass|retard\w*|losers?|bitch\w*|sluts?|whores?|bastards?|scum\w*|"
           r"dickheads?|pricks?|assholes?|arseholes?|jerks?|cunts?|motherf\w*|piece\s+of\s+(?:shit|crap|trash|garbage)|"
           r"creeps?|weirdos?|wankers?|twats?|douche\w*|skanks?|pigs?|fatso|fatty|freaks?|clowns?|failures?|imbeciles?|"
           r"cretins?|dumbo|psychos?|lowlifes?|trash|garbage|faggots?|fags?|jackass\w*)")
EN_ADJ = (r"(?:stupid|dumb|retarded|worthless|useless|pathetic|ugly|fat|disgusting|gross|waste|joke|nobody|nothing|"
          r"brainless|braindead|brain\s+dead)")

# Hinglish words that are only insults when aimed at someone ("kutta" = dog, "pagal" = crazy,
# "chakka" = a six in cricket, "moti" = pearl), so they need "tu", "tum", "abe", "hai tu"...
HI_INSULT = (r"(?:pa+gal|bewa?k(?:oo|u)f|bev(?:a)?k(?:oo|u)f|gadh[aei]|ullu|nala+yak|nikamm[aei]|kutt[aei]|kutiya|"
             r"saa?l[ai]|saale|chh?akk[ae]|hijr[ae]|hijd[aei]|tatti|suw?ar|soor|ka+lu|kallu|ka+li|moti|mota|motu|"
             r"bhainse?|ja+nwar|ganwa+r|gawa+r|gava+r|chamaa?r|bhangi|chuh[rd]a|besharam|ghatiya|ja+hil|chh?apri|"
             r"bhikh?a+ri|lode|lodu|fattu|phattu|darpok|nautanki|chirkut|chomu|kamin[aei]|haraa?mi)")
HI_DIRECT = r"(?:tu|tum|tujhe|tumhe|tujhko|tumko|tera|teri|tere|abe|oye|oy|aye|ae|you|u|saa?l[ae]|saali|chal)"
# Not an insult when the sentence goes on to praise or locate it ("tera kutta bahut cute hai").
HI_PRAISE = r"(?!\s+(?:bahut|bohot|bht|bada|badi|kitna|kitni|cute|pyara|pyari|pyaara|accha|achha|sundar|kaha|kahan|kidhar|ko\s+khana))"

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
    ("threat_violence", "high", r"\b(?:you|u|ya)\s*(?:will|'ll|ll|wil|are\s+going\s+to|r\s+going\s+to|are\s+gonna|r\s+gonna|gonna)\s+(?:surely\s+|definitely\s+)?(?:die|be\s+dead|get\s+(?:killed|hurt|beaten|stabbed|shot)|not\s+(?:live|survive|see\s+tomorrow))\b|\b(?:you|u)\s*(?:won'?t|wont)\s+(?:live|survive|see\s+tomorrow|make\s+it\s+home)\b|\byour\s+days\s+are\s+numbered\b|\bi(?:'ll|\s+will)\s+make\s+(?:you|u)\s+(?:pay|suffer|regret)\b",
     "Tells someone they will die or be harmed."),
    ("threat_violence", "high", r"\bor\s+(?:else|otherwise)\b[^.!?]{0,40}?\b(?:die|dead|kill\w*|hurt|beat\w*|stab\w*|shoot|regret|suffer|pay\s+for|see\s+what\s+happens|face\s+the\s+consequences)\b",
     "A coercive threat ('...or else') naming harm."),
    ("threat_violence", "high", r"\b(?:(?:tu|tum)\s+(?:mar|mara)\s+(?:jayega|jaega|jaoge|jayegi|jaegi)|(?:tujhe|tumhe|tujhko|tumko|tereko)\s+dekh\s+(?:lunga|lungi|lenge|loonga)|dekh\s+(?:lunga|lungi|lenge|loonga)\s+(?:tujhe|tumhe|tujhko|tumko|tereko)|zinda\s+nahi\s+(?:chhodunga|chodunga|chhodenge|chodenge|chhodungi)|(?:tera|tumhara)\s+kaam\s+tamaam)\b",
     "A threat of harm (Hinglish)."),
    ("coercion", "review", r"\b(?:(?:give|pay|return|send|transfer|hand\s+over)\s+(?:me|us|back|my|our|the\s+money|money|it\s+back)|refund|(?:paisa|paise|pese)\s+(?:de\s+de|dede|lauta|wapas)|de\s+de|dede|lauta)\b[^.!?]{0,40}\b(?:or\s+else|warna|nahi\s+to)\b|\b(?:warna\s+(?:dekh|samajh|accha\s+nahi)|nahi\s+to\s+dekh\s+lena)\b",
     "Coercive or intimidating language ('...or else')."),
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
    ("self_harm_encouragement", "high", r"\b(?:kill\s+(?:ur|yo|yor|yur)\s*self|(?:chullu\s+bhar\s+paani\s+(?:me|mein)\s+)?doob\s+(?:ke\s+)?mar\w*|marr?\s+kyu\w*\s+nahi\s+ja\w*|(?:suicide|sucide|fansi|phansi|faansi)\s+(?:kar|kr|laga)\s+(?:le|lo|lena)|zeher\s+kha\s+(?:le|lo))\b",
     "Encourages someone to harm or kill themselves."),
    # Slurs attack identity (race, religion, caste, gender, sexuality, region) and are abusive on their own.
    ("slur", "review", r"\b(?:nigg(?:er|a|ah|uh|az)s?|faggots?|fagg?ots?|fags?|trann(?:y|ies)|chinks?(?!\s+in\s+(?:the|his|her|their|its|my|our|your)\s+armou?r)|chinky|chinki\w*|pakis?|kikes?|spics?|wetbacks?|gooks?|dykes?|ragheads?|towelheads?|shemales?|sand\s*niggers?|katu(?:a|ae|e|ye)|katw[ae])\b",
     "A slur against a person's identity."),
    ("harassment", "review", rf"\b{YOU_ARE}\s+(?:such\s+an?\s+|so\s+|an?\s+|the\s+|a\s+total\s+|a\s+complete\s+)?(?:\w+\s+)?(?:{EN_NOUN}|{EN_ADJ})\b",
     "A directed insult."),
    ("harassment", "review", rf"\b(?:you|u|ya)\s+(?:(?!(?:the|that|this|those|these|a|an|my|his|her|their|our|its|at|in|on|of|to|with)\b)\w+\s+){{0,2}}?{EN_NOUN}\b|\b(?:you|u)\s+(?:look|smell|sound|act)\s+(?:so\s+|really\s+|like\s+an?\s+)?(?:\w+\s+)?(?:{EN_ADJ}|{EN_NOUN})\b|\b(?:what|such)\s+an?\s+(?:\w+\s+)?{EN_NOUN}\b",
     "A directed insult."),
    ("harassment", "review", r"\b(?:motherf\w*|mofo|cunts?|dickheads?|dumbass\w*|dumb\s+ass|jackass\w*|son\s+of\s+an?\s+(?:bitch|whore)|bitch\s*ass\w*|retard(?:s|ed)?|whores?|sluts?|slutty|skanks?|scumbags?|wankers?|twats?)\b",
     "An abusive term."),
    ("harassment", "review", rf"\b{FUCK}(?:ing|in)?\s+(?:you|u|ya|off|yo?u?r\s*self|yourself|urself|your|ur|teri|tera)\b|\bgo\s+{FUCK}\b|\bscrew\s+(?:you|u)\b|\b(?:stfu|gtfo)\b|\bf\s+off\b",
     "Profanity aimed at someone."),
    ("harassment", "review", r"\b(?:shut\s+up|(?:nobody|no\s+one|noone)\s+(?:likes|wants|loves|cares\s+about)\s+(?:you|u|ya)|everyone\s+hates\s+(?:you|u|ya)|get\s+lost|(?:you|u)\s+don'?t\s+belong|stupid\s+idiot|ugly\s+fat|fat\s+loser|dumb\s+\w+)\b",
     "Harassing or demeaning language."),
    # Strong Hinglish abuse is abusive on its own; milder words (HI_INSULT) count only when aimed at someone.
    ("harassment", "review", r"\b(?:ch(?:u|oo)\s*t(?:i?y|i)(?:a|e|o|on|apa|ape)|bho+sa?d(?:i\w*|a|e|ke)|bsdk|bkl|mkc|ma+d[ae]r\s*(?:cho+d\w*|jaa?t)|maa?\s*ch(?:o+d|u+d)\w*|b(?:a|e)?h?e?n(?:\s*cho+d\w*|cho+)|(?:behen|bhen|behan|maa|baap)\s+k[ei]\s+(?:lode|laude|lund|lavde|lawde)|(?<!niki )lauda|(?<!cum )laude|lavd[ae]|lawd[ae]|lodu|loda|lavdu|laudu|kutti|kutiya|lund(?!\s+university)|gaa+nd(?!h)\w*|gaa?ndu|jha+n?tu|jha+nt\w*|hara+m(?:i|khor|zaa?d[aei]|jaa?d[aei])|ra+ndi\w*|raand|randwa|kamina|kamine|kaminey|kamee+n[aei]y?|ullu\s+k[ae]\s+pat+h?[ae]|(?:kutt[aei]|kutiya|suw?ar|soor|randi|haram|gadh[ae]|ullu)\s+k[ie]\s+(?:aulad|bacch?[ae]|pill[ae]|nasal)|(?:maa?|behen|bhen|behan)\s+ki\s+(?:chut|chu+d\w*))\b",
     "An abusive term (Hinglish)."),
    ("harassment", "review", r"\bteri\s+(?:maa|ma|mummy|behen|bhen|behan)\s+(?:ki\s+(?:chut|aankh|chu\w*)|ka\s+bhosd\w*|ko\s+ch[ou]d\w*|ch[ou]d\w*|k[ie]\b(?!\s*\w))|\b(?:bc|mc|bkl)\b(?=\s+(?:tu|tum|kya|abe|saa?l[ae]|be|yaar|tera|teri|tere|chal|nikal|bhai|kaun|kitna|kuch|ab|ja|jaa|kar|mat|pagal|chut\w*))|\b(?:abe|tu|tum|saa?l[ae]|bhai|yaar|chal|kya|hai|ho|tha|be)\s+(?:bc|mc)\b",
     "An abusive term (Hinglish)."),
    ("harassment", "review", rf"\b{HI_DIRECT}\b(?:\s+\w+){{0,3}}?\s+{HI_INSULT}\b{HI_PRAISE}|\b{HI_INSULT}\s+(?:(?:hai|ho|h|he|hain|kya|hi|insaan|aadmi|ladka|ladki)\s+){{0,2}}(?:tu|tum|kahin\s+k[aei]|be)\b|\b{HI_INSULT}\s+{HI_INSULT}\b",
     "An insult aimed at someone (Hinglish)."),
    ("harassment", "review", r"\b(?:(?:koi|kisi\s+ko)\s+(?:bhi\s+)?(?:tujhe|tumhe|tujhko|tumko|tu|tum)\s+(?:pasand|psnd)\s+nahi|(?:tujhe|tumhe|tujhko|tumko)\s+koi\s+(?:bhi\s+)?(?:pasand|psnd|pyaar|pyar)\s+nahi|sab\s+(?:log\s+)?(?:tujhse|tumse)\s+nafrat|nikal\s+(?:yaha|yahan|idhar)\s+se|chup\s+(?:kar|kr|reh|baith)|mu+n?h\s+band\s+(?:kar|rakh|kr)|(?:teri|tumhari|tera)\s+(?:aukat|aukaat|aukad|okat)|aukaa?t\s+(?:me|mein|main)\s+(?:reh|rah)|dimaa?g\s+(?:kharab|kharaab|kharb)\s+(?:hai|h|ho)\s+(?:tera|tumhara|kya)|(?:tu|tum)\s+kisi\s+(?:kaam|kam)\s+k[aei]\s+nahi|sharam\s+(?:kar|kr|nahi\s+aati)|(?:apni\s+)?shakal\s+dekh\s+(?:apni|kabhi))\b",
     "Harassing or demeaning language (Hinglish)."),
    ("profanity", "low", r"\b(?:fuck\w*|shit\w*|bitch\w*|asshole|damn|crap|wtf)\b",
     "Profanity (not harmful on its own)."),
]
COMPILED = [(c, s, re.compile(p, re.IGNORECASE), d) for c, s, p, d in RULES]

NEGATION = re.compile(r"\b(?:never|not|wouldn'?t|won'?t|don'?t|didn'?t|nobody\s+should|no\s+one\s+should|would\s+never)\b[^.!?]{0,25}$", re.IGNORECASE)
REPORTED = re.compile(r"[\"“”‘’]|\b(?:reported|quoted|someone\s+(?:wrote|said|told|sent)|he\s+said|she\s+said|they\s+said|told\s+me|messaged\s+me|sent\s+me|received|screenshot|said\s+that)\b", re.IGNORECASE)
IDIOM = re.compile(r"\b(?:die\s+(?:laughing|of\s+(?:laughter|boredom|embarrassment|shame|cuteness))|to\s+die\s+for|killed\s+it|killing\s+it|killer\s+(?:performance|app|look|feature|deal)|dying\s+of\s+laughter|i'?m\s+dead\b(?!\s+serious)|kill\s+(?:the\s+)?(?:process|task|switch|time|bill)|shoot\s+(?:me\s+)?(?:a\s+)?(?:message|mail|email|text)|break\s+a\s+leg)\b", re.IGNORECASE)

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
    "slur": "Save the evidence, block the sender and report it to the platform; slurs break most platforms' rules.",
    "coercion": "Do not give in to pressure. Save the evidence and report it if the demands or threats continue.",
    "harassment": "Review the surrounding conversation, save evidence and consider blocking or reporting if it continues.",
}


# Most urgent advice first when several categories match.
ACTION_PRIORITY = ["self_harm_risk", "mass_violence", "threat_violence", "sextortion", "blackmail",
                   "self_harm_encouragement", "doxxing_stalking", "hate_dehumanising", "slur", "coercion", "harassment"]


def normalise(text):
    text = unicodedata.normalize("NFKC", text).translate(CONFUSABLE)
    # Masked swear words: f*ck, f**k, f***ing, b*tch, sh*t.
    text = re.sub(r"\bf(?=[\w*#]*[*#])[u*#]?[c*#]{0,2}[k*#]{1,2}(ing|in|er|ed|off)?(?!\w)",
                  lambda m: "fuck" + (m.group(1) or ""), text, flags=re.IGNORECASE)
    text = re.sub(r"\bb[*#]tch", "bitch", text, flags=re.IGNORECASE)
    text = re.sub(r"\bsh[*#]t", "shit", text, flags=re.IGNORECASE)
    # Dotted abbreviations (B.C., M.C.) and spelled-out words (k.y.s, ch.u.t.i.y.a).
    text = re.sub(r"\b([a-z])\.\s?([a-z])\.(?=\s|$)", r"\1\2", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[a-z]{1,2}(?:\s?[.\-*_]\s?[a-z]{1,2}){2,}\b", lambda m: re.sub(r"[\s.\-*_]", "", m.group(0)), text, flags=re.IGNORECASE)
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
    stronger = any(m["severity"] != "low" for m in found["matches"])
    for m in found["matches"]:
        if stronger and m["severity"] == "low":
            continue  # "profanity, not harmful on its own" would contradict a stronger finding
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
