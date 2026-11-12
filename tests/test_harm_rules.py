import unittest

from sentinel.analysis import analyze
from sentinel.harm_rules import assessment, detect, normalise
from sentinel.scan import scan

HIGH = {
    "I will kill you tomorrow after school": "threat_violence",
    "you're dead meat after class": "threat_violence",
    "main tujhe maar dunga": "threat_violence",
    "I'm going to bomb the school": "mass_violence",
    "go kill yourself nobody wants you": "self_harm_encouragement",
    "k.y.s loser": "self_harm_encouragement",
    "i want to end my life tonight": "self_harm_risk",
    "i feel like i have no reason to live": "self_harm_risk",
    "send nudes or I'll leak your photos": "sextortion",
    "pay me 5000 or i'll share your chats with everyone": "blackmail",
    "I know where you live, watch your back": "doxxing_stalking",
    "all immigrants are vermin": "hate_dehumanising",
    "Fuck you idiot dont know any thing give me my money back or else you will die": "threat_violence",
    "you will die": "threat_violence",
    "u gonna die tonight": "threat_violence",
    "pay up or else you will regret it": "threat_violence",
    "your days are numbered": "threat_violence",
    "I will make you pay": "threat_violence",
    "you won't make it home tonight": "threat_violence",
    "tu mar jayega": "threat_violence",
    "tujhe dekh lunga": "threat_violence",
    "zinda nahi chhodunga": "threat_violence",
}
COERCION = ["give me my money back or else", "pay me now or else", "refund my order or else", "paisa lauta warna dekh lena"]
REVIEW = ["you're a stupid idiot", "shut up you ugly fat loser", "you are worthless", "you are so stuuupid",
          "u r a 1d10t", "tu pagal hai kya, chal nikal bewakoof", "tu chutiya hai", "abe saale bewakoof"]
# English and Hinglish bullying: bad words, slurs and disguised spellings.
BULLYING = ["fuck you", "go fuck yourself", "you fucking idiot", "f*ck off loser", "you are a f***ing idiot",
            "you idiot", "ur so dumb", "you piece of shit", "you're a dumbass", "what a retard", "son of a bitch",
            "you ugly bitch", "stupid cunt", "you motherfucker", "nobody likes u", "you look so fat",
            "bc kya kar raha hai", "B.C. tu pagal hai", "bsdk", "bkl", "chutiye", "ch.u.t.i.y.a", "bhosdike",
            "maderchod", "behen ke lode", "teri maa ki chut", "gaandu", "jhaatu", "haramkhor", "haraami",
            "kutte ki aulad", "kaminey", "saala kutta", "hijra hai tu", "pagal ho kya tum", "moti bhains",
            "ullu ka pattha", "nikal yahan se", "chup kar be", "teri aukat kya hai", "tu kisi kaam ka nahi"]
SLURS = ["you faggot", "nigger", "n1gga", "tranny", "dirty paki", "chinki", "katua"]
SELF_HARM_HINGLISH = ["kill urself", "chullu bhar paani mein doob mar", "fansi laga le"]
BENIGN = ["thank you so much", "have you read moby dick", "did you see that clown at the circus",
          "he graduated magna cum laude", "Lund University in Sweden", "Mahatma Gandhi was a leader",
          "Niki Lauda won the race", "India hit a chakka in the last over", "yeh phone nikamma hai",
          "tera kutta bahut cute hai", "teri maa ki tabiyat kaisi hai", "Ben Cho is my classmate",
          "a chink in the armour", "the bc ratio is low", "mc donalds is near", "Scunthorpe is a town",
          "Pakistan cricket team", "kya baat hai yaar", "tum kaise ho", "shut the door please","Have a great day!", "This movie killed it, totally killer performance", "I hate Mondays",
          "I would never hurt you", "Please shoot me an email when you are free", "kill the process and restart the server",
          "damn this traffic", "Call 112 in an emergency", "mera kutta bahut cute hai", "Rome fell in 476 BC",
          "We went to McDonald's", "yeh gaana pagal kar dega", "I'm dead 😂 that meme",
          "you will die laughing at this video", "this cake is to die for", "everyone will die someday",
          "plants will die without water", "eat your vegetables or else no dessert", "or else what?",
          "send the report by friday, or else the deadline passes"]


class DetectionTests(unittest.TestCase):
    def test_high_severity_categories(self):
        for text, category in HIGH.items():
            found = detect(text)
            self.assertEqual(found["level"], "high", text)
            self.assertIn(category, found["categories"], text)

    def test_demands_with_or_else_are_coercion(self):
        for text in COERCION:
            found = detect(text)
            self.assertEqual(found["level"], "review", text)
            self.assertIn("coercion", found["categories"], text)

    def test_insult_plus_threat_reports_both(self):
        found = detect("Fuck you idiot dont know any thing give me my money back or else you will die")
        self.assertEqual(found["categories"][0], "threat_violence")
        self.assertIn("harassment", found["categories"])
        self.assertTrue(assessment("you will die")["action"].startswith("Do not engage"))

    def test_directed_insults_need_review(self):
        for text in REVIEW:
            self.assertEqual(detect(text)["level"], "review", text)

    def test_english_and_hinglish_bullying_needs_review(self):
        for text in BULLYING:
            self.assertEqual(detect(text)["level"], "review", text)

    def test_slurs_are_flagged_with_their_own_category(self):
        for text in SLURS:
            found = detect(text)
            self.assertEqual(found["level"], "review", text)
            self.assertIn("slur", found["categories"], text)
        self.assertIn("report", assessment("tranny")["action"])

    def test_hinglish_self_harm_encouragement_is_high(self):
        for text in SELF_HARM_HINGLISH:
            self.assertIn("self_harm_encouragement", detect(text)["categories"], text)
            self.assertEqual(detect(text)["level"], "high", text)

    def test_benign_text_and_idioms_are_not_flagged(self):
        for text in BENIGN:
            self.assertEqual(detect(text)["level"], "low_observed_concern", text)

    def test_reported_or_quoted_threats_become_review(self):
        self.assertEqual(detect('He said "I will kill you" in the group chat')["level"], "review")
        evidence = assessment('She reported that someone wrote "you are stupid" in the chat.')["evidence"]
        self.assertTrue(any("quoted or reported" in e for e in evidence))

    def test_self_harm_is_never_downgraded_and_gets_support_resources(self):
        result = assessment('My friend messaged me "I want to kill myself"')
        self.assertEqual(result["level"], "high")
        self.assertIn("14416", result["action"])

    def test_most_urgent_advice_wins(self):
        self.assertTrue(assessment("I will kill you tomorrow, I know where you live")["action"].startswith("Do not engage"))
        self.assertIn("14416", assessment("i want to die, everyone hates you")["action"])

    def test_normalisation_undoes_disguises(self):
        self.assertIn("stupid", normalise("stuuupid"))
        self.assertIn("idiot", normalise("1d10t"))
        self.assertIn("kys", normalise("k.y.s"))
        self.assertIn("112", normalise("call 112"))

    def test_empty_text(self):
        self.assertEqual(detect("   ")["level"], "not_assessed")
        self.assertEqual(assessment("")["level"], "not_assessed")


class IntegrationTests(unittest.TestCase):
    def test_analyze_reports_level_categories_and_method(self):
        harm = analyze({"message": "I will kill you after school"})["harmful_content"]
        self.assertEqual(harm["level"], "high")
        self.assertEqual(harm["categories"], ["threat_violence"])
        self.assertIn("rules", harm["method"])

    def test_scan_marks_dangerous_language_high(self):
        results = {r["id"]: r for r in scan({"items": [
            {"id": "threat", "text": "go kill yourself loser, nobody wants you"},
            {"id": "insult", "text": "you are such a stupid idiot honestly"},
            {"id": "fine", "text": "see you at lunch near the library"},
            {"id": "user", "text": "Fuck you idiot dont know any thing give me my money back or else you will die"}]})["results"]}
        self.assertEqual(results["user"]["severity"], "high")
        self.assertTrue(any("die or be harmed" in e or "threat" in e.lower() for e in results["user"]["evidence"]))
        self.assertEqual(results["threat"]["severity"], "high")
        self.assertEqual(results["insult"]["severity"], "review")
        self.assertEqual(results["fine"]["severity"], "none")
        self.assertIn("block the sender", results["threat"]["action"])


if __name__ == "__main__":
    unittest.main()
