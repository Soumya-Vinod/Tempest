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
    "বিশ কুড়ি ত্রিশ তিরিশ চল্লিশ পঞ্চাশ ষাট সত্তর আশি নব্বই শত শো একশো হাজার লাখ লক্ষ কোটি "
    "শূন্য"  # zero
).split()
_BN_COUNTED = "দু দুই তিন চার পাঁচ ছয় সাত আট নয় দশ".split()  # + টি / টা / টো / জন
_BN_COUNT_SUFFIXES = ("টি", "টা", "টো", "জন")
_HI_WORDS = (
    "दो तीन चार पाँच पांच छह छः सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह पन्द्रह सोलह सत्रह "
    "अठारह उन्नीस बीस तीस चालीस पचास साठ सत्तर अस्सी नब्बे सौ हज़ार हजार लाख करोड़ करोड "
    "शून्य"  # zero
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

# --- Auto-repair: a count written in words -> its count placeholder ---------------------------
#
# Models (Groq especially) write "two hospitals" / "দুটো হাসপাতাল" / "दोनों" although the prompt
# says to use {{..._count}}. Before the number check, a number word whose value equals a count
# citation of the block is replaced by that count's placeholder (any match: they render the same
# number). A word with no matching count stays, so the check still rejects it; digits are never
# repaired. Every repair is returned for the audit log.

_EN_VALUES = {
    **{
        w: i
        for i, w in enumerate(
            "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
            "fifteen sixteen seventeen eighteen nineteen twenty".split()
        )
    },
    "both": 2,
}
_BN_BASE = {"শূন্য": 0, "দু": 2, "দুই": 2, "তিন": 3, "চার": 4, "পাঁচ": 5, "ছয়": 6, "সাত": 7,
            "আট": 8, "নয়": 9, "দশ": 10}  # fmt: skip
_BN_VALUES = {
    **{w: v for w, v in _BN_BASE.items() if w not in ("দু", "নয়")},  # bare দু / নয় aren't counts
    **{w + sfx: v for w, v in _BN_BASE.items() if v for sfx in _BN_COUNT_SUFFIXES},
}
_HI_VALUES = {
    "शून्य": 0, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6, "छः": 6, "सात": 7,
    "आठ": 8, "नौ": 9, "दस": 10,
    "दोनों": 2, "तीनों": 3, "चारों": 4, "पाँचों": 5, "पांचों": 5, "छहों": 6, "सातों": 7,
    "आठों": 8, "दसों": 10,
}  # fmt: skip
REPAIR_VALUES = {"en": _EN_VALUES, "bn": _BN_VALUES, "hi": _HI_VALUES}
_REPAIR_RE = {
    "en": _words_re(list(_EN_VALUES), re.IGNORECASE),
    "bn": _words_re(list(_BN_VALUES)),
    "hi": _words_re(list(_HI_VALUES)),
}
# "both wind and surge": "both ... and" joins two things; it doesn't count them.
_BOTH_AND = re.compile(r"^\s+(?:\S+\s+){0,3}and\b", re.IGNORECASE)


@dataclass(frozen=True)
class Repair:
    language: str
    field: str
    original: str
    placeholder: str

    def as_dict(self) -> dict:
        return {
            "language": self.language,
            "field": self.field,
            "original": self.original,
            "placeholder": self.placeholder,
        }


def _count_keys(citations: list[Citation]) -> dict[float, str]:
    """Count value -> the first count key with it (citation order)."""
    out: dict[float, str] = {}
    for c in citations:
        if c.key.endswith(COUNT_SUFFIX) and not isinstance(c.value, str):
            out.setdefault(float(c.value), c.key)
    return out


def _repair_text(
    text: str, language: str, counts: dict[float, str], field: str, found: list[Repair]
) -> str:
    values = REPAIR_VALUES[language]

    def replace(m: re.Match) -> str:
        word = m.group(0)
        value = values[word.casefold() if language == "en" else word]
        key = counts.get(float(value))
        if key is None:
            return word  # no count with this value: left for the number check to reject
        if language == "en" and word.casefold() == "both" and _BOTH_AND.match(text[m.end() :]):
            return word
        placeholder = f"{{{{{key}}}}}"
        # Bengali counted forms keep a classifier: দুটো হাসপাতাল -> {{key}}টি হাসপাতাল.
        suffix = next((s for s in _BN_COUNT_SUFFIXES if language == "bn" and word.endswith(s)), "")
        replacement = placeholder + ("জন" if suffix == "জন" else "টি" if suffix else "")
        found.append(Repair(language, field, word, placeholder))
        return replacement

    # Placeholders are left alone: only the text between them is repaired.
    parts = re.split(r"(\{\{\s*[a-z0-9_]+\s*\}\})", text)
    return "".join(
        part if PLACEHOLDER.fullmatch(part) else _REPAIR_RE[language].sub(replace, part)
        for part in parts
    )


def repair_counts(
    templates: AdvisoryTexts, citations: list[Citation]
) -> tuple[AdvisoryTexts, list[Repair]]:
    """The templates with counts written in words replaced by matching count placeholders."""
    counts = _count_keys(citations)
    found: list[Repair] = []
    if not counts:
        return templates, found
    out = {}
    for lang in LANGUAGES:
        t = getattr(templates, lang)
        out[lang] = AdvisoryText(
            headline=_repair_text(t.headline, lang, counts, "headline", found),
            body=_repair_text(t.body, lang, counts, "body", found),
            actions=[
                _repair_text(a, lang, counts, f"actions[{i}]", found)
                for i, a in enumerate(t.actions)
            ],
        )
    return (AdvisoryTexts(**out) if found else templates), found


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


_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")
COUNT_SUFFIX = "_count"
STANDIN_COUNT = "standin_count"


def fact_problems(templates: AdvisoryTexts, citations: list[Citation]) -> list[Problem]:
    """Rules that depend on the figures: one count per statement (no sentence with two count
    placeholders of equal value, e.g. a total and an equal subtotal). (The no-shelters action is
    added by the server: add_shelter_action.)"""
    values = {c.key: c.value for c in citations}
    problems = []
    for lang in LANGUAGES:
        t = getattr(templates, lang)
        for field, text in _fields(t):
            for sentence in _SENTENCE_END.split(text):
                counts = [
                    k
                    for k in dict.fromkeys(PLACEHOLDER.findall(sentence))
                    if k.endswith(COUNT_SUFFIX) and not isinstance(values.get(k), str)
                ]
                for i, a in enumerate(counts):
                    for b in counts[i + 1 :]:
                        if a in values and b in values and values[a] == values[b]:
                            problems.append(Problem(lang, field, "duplicate_count", f"{a}={b}"))
    return problems


# --- No mapped shelters: one fixed, pre-translated action, added by the server ------------------

# The model is told not to write shelter actions when a block has none mapped; the server adds
# this one to every language instead (no figures, so nothing for the number check).
NO_SHELTERS_ACTION = {
    "en": (
        "No shelters are mapped in this block: identify safe concrete buildings (schools, "
        "panchayat offices) locally before the storm."
    ),
    "bn": (
        "এই ব্লকে কোনো আশ্রয়কেন্দ্র চিহ্নিত নেই: ঝড়ের আগেই স্থানীয়ভাবে নিরাপদ পাকা ভবন "
        "(স্কুল, পঞ্চায়েত অফিস) খুঁজে বের করুন।"
    ),
    "hi": (
        "इस ब्लॉक में कोई आश्रय स्थल चिह्नित नहीं है: तूफ़ान से पहले स्थानीय स्तर पर सुरक्षित "
        "पक्की इमारतें (स्कूल, पंचायत कार्यालय) पहचानें।"
    ),
}
MAX_ACTIONS = 5  # AdvisoryText: 3 to 5 actions


def no_shelters(citations: list[Citation]) -> bool:
    return any(c.key == STANDIN_COUNT and c.value == 0 for c in citations)


def add_shelter_action(
    templates: AdvisoryTexts, citations: list[Citation]
) -> tuple[AdvisoryTexts, list[Problem]]:
    """With no mapped shelters: the fixed action appended to every language (once). A language
    that already has MAX_ACTIONS actions can't take it: that is a problem for a retry."""
    if not no_shelters(citations):
        return templates, []
    out, problems = {}, []
    for lang in LANGUAGES:
        t = getattr(templates, lang)
        action = NO_SHELTERS_ACTION[lang]
        if action in t.actions:
            out[lang] = t
        elif len(t.actions) >= MAX_ACTIONS:
            out[lang] = t
            problems.append(Problem(lang, "actions", "too_many_actions", str(len(t.actions))))
        else:
            out[lang] = AdvisoryText(headline=t.headline, body=t.body, actions=[*t.actions, action])
    return AdvisoryTexts(**out), problems


def check(
    templates: AdvisoryTexts,
    keys: set[str],
    required: dict[str, set[str]] | None = None,
    citations: list[Citation] | None = None,
) -> list[Problem]:
    """Everything wrong with a set of templates: stray numbers, unknown placeholders, (for
    edits) placeholders removed from `required` (per language), and, given the citations, the
    fact rules (fact_problems)."""
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
    if citations is not None:
        problems += fact_problems(templates, citations)
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


# A unit the model wrote right after a placeholder that already renders one ("{{x}} minutes" ->
# "20 min minutes"): the repeated unit word is dropped. Keyed by the citation's unit.
_UNIT_WORDS = {
    "min": {
        "en": ["minutes", "minute", "mins", "min"],
        "bn": ["মিনিট"],
        "hi": ["मिनट"],
    },
    "h": {
        "en": ["hours", "hour", "hrs", "hr", "h"],
        "bn": ["ঘণ্টা", "ঘন্টা"],
        "hi": ["घंटे", "घंटा", "घण्टे", "घण्टा"],
    },
    "km": {
        "en": ["kilometres", "kilometre", "kilometers", "kilometer", "kms", "km"],
        "bn": ["কিলোমিটার", "কিমি"],
        "hi": ["किलोमीटर", "किमी"],
    },
    "m": {
        "en": ["metres", "metre", "meters", "meter", "m"],
        "bn": ["মিটার"],
        "hi": ["मीटर"],
    },
    "m/s": {  # rendered as km/h
        "en": ["km/h", "kmph", "kph", "km per hour"],
        "bn": ["কিমি/ঘণ্টা", "কিমি/ঘন্টা", "কিলোমিটার/ঘণ্টা"],
        "hi": ["किमी/घंटा", "किमी/घण्टा", "किलोमीटर/घंटा"],
    },
}
_UNIT_RE = {
    (unit, lang): re.compile(
        rf"\s*(?:{'|'.join(map(re.escape, sorted(words, key=len, reverse=True)))})(?!{_LETTER})",
        re.IGNORECASE if lang == "en" else 0,
    )
    for unit, by_lang in _UNIT_WORDS.items()
    for lang, words in by_lang.items()
}


def fill(text: str, citations: dict[str, Citation], language: str) -> str:
    out: list[str] = []
    pos = 0
    for m in PLACEHOLDER.finditer(text):
        out.append(text[pos : m.start()])
        c = citations[m.group(1)]
        filled = format_value(c, language)
        if language == "en" and filled and _starts_sentence(text, m.start()):
            filled = filled[0].upper() + filled[1:]
        out.append(filled)
        pos = m.end()
        repeat = _UNIT_RE.get((c.unit or "", language))
        if repeat and not isinstance(c.value, str) and (dup := repeat.match(text, pos)):
            pos = dup.end()
    out.append(text[pos:])
    return "".join(out)


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
