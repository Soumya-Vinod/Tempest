"""Placeholder filling and the number check for advisory text (contracts.md §4.5).

Templates refer to figures only as {{key}} placeholders from the citations. Before filling, a
template is rejected if it contains any digit (any script) or a number word from NUMBER_WORDS
outside a placeholder: every figure in an advisory must come from the engine. Filling uses
Bengali numerals for bn and Latin digits for en and hi; wind (m/s) is written in km/h to the
nearest 5, surge (m) to 0.1 m (the citations keep the full values). Block names and unnamed
facilities are written in the text's language, and in English a value that starts a sentence is
capitalised. The exercise label is added to each body after the check (its "2020" is not
Gemini's).
"""

import re
from dataclasses import dataclass

from app.risk.blocks import local_names
from app.schemas import AdvisoryText, AdvisoryTexts, Citation

LANGUAGES = ("en", "bn", "hi")
PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")
_DIGIT = re.compile(r"\d")  # str patterns match every Unicode decimal digit (০-৯, ०-९, ...)

EXERCISE_PREFIX = {
    "en": "[EXERCISE: Cyclone Amphan 2020 replay]",
    "bn": "[মহড়া: ঘূর্ণিঝড় আমফান ২০২০ রিপ্লে]",
    "hi": "[अभ्यास: चक्रवात अम्फान 2020 रीप्ले]",
}

# --- Number words: the only place they are listed (prompt.py states the same rule) ------------
# en: zero to twenty, thirty to ninety, hundred, thousand, lakh, crore, dozen, half, double,
# twice, triple. bn and hi: two upward, plus hundred / thousand / lakh / crore. "One" is not
# listed in bn and hi (এক / एक also mean "a"); neither is bare bn নয় ("nine", but also "is
# not"): only its counted forms (নয়টি, নয়জন) are.
_EN_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty "
    "ninety half double twice triple"
).split()
_EN_PLURAL = "hundred thousand lakh crore dozen".split()
_BN_WORDS = (
    "দুই তিন চার পাঁচ ছয় সাত আট দশ এগারো বারো তেরো চোদ্দ চৌদ্দ পনেরো ষোলো সতেরো আঠারো উনিশ "
    "বিশ কুড়ি ত্রিশ তিরিশ চল্লিশ পঞ্চাশ ষাট সত্তর আশি নব্বই শত শো একশো হাজার লাখ লক্ষ কোটি"
).split()
_BN_COUNTED = "দু দুই তিন চার পাঁচ ছয় সাত আট নয় দশ".split()  # + টি / টা / টো / জন
_BN_COUNT_SUFFIXES = ("টি", "টা", "টো", "জন")
_HI_WORDS = (
    "दो तीन चार पाँच पांच छह छः सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह पन्द्रह सोलह सत्रह "
    "अठारह उन्नीस बीस तीस चालीस पचास साठ सत्तर अस्सी नब्बे सौ हज़ार हजार लाख करोड़ करोड"
).split()
_HI_ALL = "दोनों तीनों चारों पाँचों पांचों छहों सातों आठों दसों".split()  # "both", "all three"...

NUMBER_WORDS: dict[str, list[str]] = {
    "en": [*_EN_WORDS, *_EN_PLURAL, *(w + "s" for w in _EN_PLURAL)],
    "bn": [*_BN_WORDS, *(w + s for w in _BN_COUNTED for s in _BN_COUNT_SUFFIXES)],
    "hi": [*_HI_WORDS, *_HI_ALL],
}

# A word is a maximal run of letters and combining marks: for bn and hi, \b is not enough
# (vowel signs are marks, not \w, so তিন would match inside তিনি "he/she").
_LETTER = r"[\wऀ-ॿঀ-৿]"


def _words_re(words: list[str], flags: int = 0) -> re.Pattern:
    alternation = "|".join(sorted(map(re.escape, words), key=len, reverse=True))
    return re.compile(rf"(?<!{_LETTER})(?:{alternation})(?!{_LETTER})", flags)


_NUMBER_WORD_RE = {
    "en": _words_re(NUMBER_WORDS["en"], re.IGNORECASE),
    "bn": _words_re(NUMBER_WORDS["bn"]),
    "hi": _words_re(NUMBER_WORDS["hi"]),
}

# --- Filling ------------------------------------------------------------------------------------

_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
UNITS = {
    "m": {"en": "m", "bn": "মিটার", "hi": "मीटर"},
    "km/h": {"en": "km/h", "bn": "কিমি/ঘণ্টা", "hi": "किमी/घंटा"},
    "km": {"en": "km", "bn": "কিমি", "hi": "किमी"},
    "min": {"en": "min", "bn": "মিনিট", "hi": "मिनट"},
    "h": {"en": "hours", "bn": "ঘণ্টা", "hi": "घंटे"},
}
# bn / hi for the enumerated text values in facts.py (names are never translated).
TEXT = {
    "storm surge": ("জলোচ্ছ্বাস", "तूफानी लहर"),
    "wind": ("ঝোড়ো হাওয়া", "तेज़ हवा"),
    "flood susceptibility": ("বন্যাপ্রবণতা", "बाढ़ की आशंका"),
    "isolated facilities": ("বিচ্ছিন্ন স্বাস্থ্যকেন্দ্র ও আশ্রয়", "कटे हुए स्वास्थ्य केंद्र और आश्रय"),
    "cut roads": ("বিচ্ছিন্ন রাস্তা", "कटी हुई सड़कें"),
    "cut substations": ("বিকল সাবস্টেশন", "बंद सबस्टेशन"),
    "population density": ("জনঘনত্ব", "जनसंख्या घनत्व"),
    "hospital access": ("হাসপাতালে পৌঁছনোর সুযোগ", "अस्पताल तक पहुँच"),
    "low literacy": ("স্বল্প সাক্ষরতা", "कम साक्षरता"),
    "few mapped shelters": ("চিহ্নিত আশ্রয়কেন্দ্রের অভাব", "चिह्नित आश्रयों की कमी"),
    "direct hazard": ("সরাসরি দুর্যোগ", "सीधा खतरा"),
    "cut off by the storm": ("ঝড়ে বিচ্ছিন্ন", "तूफान से कटा हुआ"),
    "ferry suspended by wind": ("ঝোড়ো হাওয়ায় ফেরি বন্ধ", "तेज़ हवा से फेरी बंद"),
    "ferry route closed by storm surge": ("জলোচ্ছ্বাসে ফেরিপথ বন্ধ", "तूफानी लहर से फेरी मार्ग बंद"),
    "road flooded by storm surge": ("জলোচ্ছ্বাসে রাস্তা প্লাবিত", "तूफानी लहर से सड़क जलमग्न"),
    "road blocked by wind": ("ঝোড়ো হাওয়ায় রাস্তা বন্ধ", "तेज़ हवा से सड़क बंद"),
    "road flooded": ("রাস্তা প্লাবিত", "सड़क जलमग्न"),
    "ferry route closed by flooding": ("বন্যায় ফেরিপথ বন্ধ", "बाढ़ से फेरी मार्ग बंद"),
}
_MONTHS = {"May": ("মে", "मई")}
KMH_STEP = 5  # wind in the text: km/h, to the nearest 5
SENTENCE_END = (". ", "! ", "? ")

# Facilities with no name, by facility_level (health) or shelter_kind (stand-in shelters):
# kind -> (citation value, en, bn, hi). facts.py cites the first; the text uses the others.
UNNAMED: dict[str, tuple[str, str, str, str]] = {
    "hospital": (
        "Unnamed hospital",
        "an unnamed hospital",
        "নামহীন একটি হাসপাতাল",
        "एक अनाम अस्पताल",
    ),
    "health_centre": (
        "Unnamed health centre",
        "an unnamed health centre",
        "নামহীন একটি স্বাস্থ্যকেন্দ্র",
        "एक अनाम स्वास्थ्य केंद्र",
    ),
    "school_proxy": (
        "Unnamed school (stand-in shelter)",
        "an unnamed school (stand-in shelter)",
        "নামহীন একটি বিদ্যালয় (বিকল্প আশ্রয়)",
        "एक अनाम विद्यालय (वैकल्पिक आश्रय)",
    ),
    "community_proxy": (
        "Unnamed community centre (stand-in shelter)",
        "an unnamed community centre (stand-in shelter)",
        "নামহীন একটি কমিউনিটি সেন্টার (বিকল্প আশ্রয়)",
        "एक अनाम सामुदायिक केंद्र (वैकल्पिक आश्रय)",
    ),
    "public_building_proxy": (
        "Unnamed public building (stand-in shelter)",
        "an unnamed public building (stand-in shelter)",
        "নামহীন একটি সরকারি ভবন (বিকল্প আশ্রয়)",
        "एक अनाम सरकारी भवन (वैकल्पिक आश्रय)",
    ),
}
_UNNAMED_TEXT = {
    cited: dict(zip(LANGUAGES, texts, strict=True)) for cited, *texts in UNNAMED.values()
}


@dataclass(frozen=True)
class Problem:
    language: str
    field: str  # headline, body, actions[2]
    kind: str  # digit, number_word, unknown_placeholder, removed_placeholder
    text: str  # the offending digit / word / key

    def __str__(self) -> str:
        return f"{self.language}.{self.field}: {self.kind} {self.text!r}"


def _fields(t: AdvisoryText) -> list[tuple[str, str]]:
    return [
        ("headline", t.headline),
        ("body", t.body),
        *((f"actions[{i}]", a) for i, a in enumerate(t.actions)),
    ]


def placeholder_keys(t: AdvisoryText) -> set[str]:
    return {k for _, text in _fields(t) for k in PLACEHOLDER.findall(text)}


def number_problems(text: str, language: str) -> list[tuple[str, str]]:
    """(kind, match) for every digit or number word outside the placeholders."""
    bare = PLACEHOLDER.sub(" ", text)
    found = [("digit", m.group()) for m in _DIGIT.finditer(bare)]
    found += [("number_word", m.group()) for m in _NUMBER_WORD_RE[language].finditer(bare)]
    return found


def check(
    templates: AdvisoryTexts, keys: set[str], required: dict[str, set[str]] | None = None
) -> list[Problem]:
    """Everything wrong with a set of templates: stray numbers, unknown placeholders and (for
    edits) placeholders removed from `required` (per language)."""
    problems = []
    for lang in LANGUAGES:
        t = getattr(templates, lang)
        for field, text in _fields(t):
            problems += [Problem(lang, field, kind, m) for kind, m in number_problems(text, lang)]
            problems += [
                Problem(lang, field, "unknown_placeholder", k)
                for k in PLACEHOLDER.findall(text)
                if k not in keys
            ]
        if required:
            missing = required.get(lang, set()) - placeholder_keys(t)
            problems += [Problem(lang, "*", "removed_placeholder", k) for k in sorted(missing)]
    return problems


def _number(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}".rstrip("0").rstrip(".")


def format_value(c: Citation, language: str) -> str:
    v = c.value
    if isinstance(v, str):
        if c.key.endswith("_name") and v in _UNNAMED_TEXT:
            text = _UNNAMED_TEXT[v][language]
        elif c.key == "block_name" and language != "en":
            text = local_names().get(v, {}).get(language, v)
        elif c.key.endswith("_name") or c.key.endswith("_route") or language == "en":
            text = v
        elif v in TEXT:
            text = TEXT[v][LANGUAGES.index(language) - 1]
        else:
            text = v
            for en, (bn, hi) in _MONTHS.items():
                text = text.replace(en, bn if language == "bn" else hi)
        is_name = c.key.endswith("_name") or c.key.endswith("_route")
        return text.translate(_BN_DIGITS) if language == "bn" and not is_name else text
    unit_key = c.unit or ""
    if unit_key == "m/s":  # half a step rounds up (not to even)
        number, unit_key = str(int(v * 3.6 / KMH_STEP + 0.5) * KMH_STEP), "km/h"
    elif unit_key == "m":
        number = f"{v:.1f}"
    else:
        number = _number(v)
    if language == "bn":
        number = number.translate(_BN_DIGITS)
    unit = UNITS.get(unit_key, {}).get(language, c.unit)
    if unit == "hours" and number == "1":
        unit = "hour"
    return f"{number} {unit}" if unit else number


def _starts_sentence(text: str, pos: int) -> bool:
    before = text[:pos]
    return not before.strip() or before.endswith(SENTENCE_END)


def fill(text: str, citations: dict[str, Citation], language: str) -> str:
    def value(m: re.Match) -> str:
        filled = format_value(citations[m.group(1)], language)
        if language == "en" and filled and _starts_sentence(text, m.start()):
            filled = filled[0].upper() + filled[1:]
        return filled

    return PLACEHOLDER.sub(value, text)


def render(templates: AdvisoryTexts, citations: list[Citation]) -> AdvisoryTexts:
    """Filled texts, each body starting with the exercise label. Check the templates first."""
    by_key = {c.key: c for c in citations}
    out = {}
    for lang in LANGUAGES:
        t = getattr(templates, lang)
        out[lang] = AdvisoryText(
            headline=fill(t.headline, by_key, lang),
            body=f"{EXERCISE_PREFIX[lang]} {fill(t.body, by_key, lang)}",
            actions=[fill(a, by_key, lang) for a in t.actions],
        )
    return AdvisoryTexts(**out)
