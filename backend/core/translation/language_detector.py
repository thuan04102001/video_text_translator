import re
from typing import List

try:
    from langdetect import DetectorFactory, LangDetectException, detect_langs

    DetectorFactory.seed = 0
except Exception:  # pragma: no cover - optional dependency guard
    LangDetectException = Exception
    detect_langs = None

DEFAULT_OCR_LANGUAGES = ["en"]
SUB_FAIL_TEXT = "SUB FAIL"

# Short meme/UI words are intentionally neutral. They are too common across
# English and non-English memes, so they should not decide the whole video.
IGNORED_TOKENS = {
    "a",
    "an",
    "and",
    "be",
    "by",
    "i",
    "im",
    "in",
    "is",
    "it",
    "me",
    "my",
    "no",
    "of",
    "on",
    "or",
    "pov",
    "the",
    "to",
    "u",
    "yo",
}

MEME_LABELS = {
    "baby",
    "boy",
    "boys",
    "bro",
    "dad",
    "daddy",
    "girl",
    "girls",
    "kid",
    "kids",
    "mama",
    "me",
    "mom",
    "mommy",
    "mother",
    "papa",
    "son",
    "teacher",
}

ENGLISH_WORDS = {
    "about",
    "after",
    "again",
    "all",
    "already",
    "always",
    "anything",
    "are",
    "asked",
    "around",
    "babies",
    "because",
    "been",
    "before",
    "browser",
    "buy",
    "buying",
    "called",
    "can",
    "cant",
    "car",
    "class",
    "come",
    "coming",
    "could",
    "delete",
    "doctor",
    "does",
    "doing",
    "dont",
    "fall",
    "falling",
    "feel",
    "feels",
    "find",
    "for",
    "forgot",
    "friend",
    "girlfriend",
    "from",
    "gas",
    "get",
    "going",
    "good",
    "got",
    "gta",
    "had",
    "has",
    "have",
    "having",
    "he",
    "help",
    "her",
    "his",
    "history",
    "holding",
    "how",
    "if",
    "into",
    "lawyer",
    "laywer",
    "leaving",
    "logic",
    "like",
    "look",
    "looking",
    "looks",
    "mama",
    "man",
    "married",
    "moments",
    "movies",
    "new",
    "not",
    "nothing",
    "only",
    "phone",
    "parties",
    "put",
    "reality",
    "remembering",
    "school",
    "sick",
    "something",
    "store",
    "summer",
    "evening",
    "every",
    "sends",
    "send",
    "woman",
    "womans",
    "divorce",
    "agreement",
    "teaches",
    "teaching",
    "that",
    "their",
    "then",
    "there",
    "they",
    "thailand",
    "this",
    "tomorrow",
    "trying",
    "was",
    "we",
    "went",
    "what",
    "when",
    "where",
    "while",
    "who",
    "why",
    "with",
    "without",
    "world",
    "would",
    "you",
    "your",
    "youre",
}

SPANISH_STRONG_MARKERS = {
    "alla",
    "amiga",
    "amigas",
    "amigo",
    "amigos",
    "anos",
    "asando",
    "ayuda",
    "boda",
    "bulgaria",
    "carne",
    "casa",
    "chica",
    "chicas",
    "chico",
    "chicos",
    "clase",
    "como",
    "cocinando",
    "conduciendo",
    "cuando",
    "cumpleanos",
    "dejo",
    "donde",
    "dormir",
    "echar",
    "ella",
    "ellos",
    "estan",
    "fuenda",
    "gente",
    "hermana",
    "hermano",
    "hombre",
    "iphone",
    "telefono",
    "lanzamiento",
    "llamada",
    "llamado",
    "llamemos",
    "menor",
    "metros",
    "minutos",
    "mimo",
    "misma",
    "mismo",
    "necesitamos",
    "necsitamos",
    "negocios",
    "nino",
    "nina",
    "ninos",
    "ninas",
    "padres",
    "pesar",
    "pizarra",
    "probe",
    "primer",
    "profesor",
    "profesora",
    "pronto",
    "reaccion",
    "tenda",
    "tienda",
    "tiene",
    "tienes",
    "tengo",
    "todo",
    "voy",
    "vuelvo",
    "estoy",
    "hace",
    "harta",
    "comer",
    "gato",
    "llegaste",
    "radiografia",
    "radiologo",
    "segura",
    "totalmente",
    "verdad",
    "salario",
    "promedio",
    "estados",
    "unidos",
    "favorito",
    "sitio",
    "medio",
    "turbio",
    "supersticiones",
    "tipos",
    "cuerpo",
    "diferentes",
}

SPANISH_CONTEXT_MARKERS = {
    "con",
    "de",
    "del",
    "dia",
    "el",
    "en",
    "es",
    "esta",
    "fue",
    "la",
    "las",
    "lo",
    "los",
    "al",
    "mi",
    "para",
    "que",
    "se",
    "ser",
    "solo",
    "su",
    "un",
    "una",
    "vida",
    "por",
    "tan",
    "y",
}

PORTUGUESE_MARKERS = {"homem", "mae", "nao", "pai", "quando", "voce"}

FRENCH_STRONG_MARKERS = {
    "ami",
    "amie",
    "avec",
    "bonjour",
    "dans",
    "fille",
    "garcon",
    "lancement",
    "merci",
    "mon",
    "pour",
}

ROMANCE_LANGDETECT_CODES = {"ca", "es", "fr", "it", "pt", "ro"}


def normalize_translation_lang(code: str) -> str:
    normalized = str(code or "").strip().lower().replace("-", "_")

    aliases = {
        "auto": "auto",
        "ch_sim": "zh",
        "ch_tra": "zh",
        "zh_cn": "zh",
        "zh_tw": "zh",
        "cn": "zh",
        "pt_br": "pt",
        "pt_pt": "pt",
    }

    return aliases.get(normalized, normalized or "en")


def default_ocr_languages(languages: List[str] | None = None) -> List[str]:
    return list(DEFAULT_OCR_LANGUAGES)


def _tokenize_for_language(text: str) -> List[str]:
    normalized = str(text or "").lower().replace("\u2019", "'").replace("`", "'")
    normalized = re.sub(r"\b([a-z]+)'s\b", r"\1", normalized)
    normalized = re.sub(r"\b([a-z]+)n't\b", r"\1nt", normalized)
    return re.findall(r"[a-z]+", normalized)


def _has_non_english_script(text: str) -> str | None:
    if re.search(r"[\u0400-\u04ff]", text):
        return "ru"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u0e00-\u0e7f]", text):
        return "th"
    if re.search(r"[\u0600-\u06ff]", text):
        return "ar"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\u3130-\u318f\uac00-\ud7af]", text):
        return "ko"
    return None


def _has_vietnamese_diacritic(text: str) -> bool:
    return bool(
        re.search(
            "[\u00e0\u1ea1\u1ea3\u00e3\u00e1\u0103\u1eb1\u1eaf\u1eb7\u1eb3"
            "\u1eb5\u00e2\u1ea7\u1ea5\u1ead\u1ea9\u1eab\u00e8\u1eb9"
            "\u1ebb\u1ebd\u00e9\u00ea\u1ec1\u1ebf\u1ec7\u1ec3\u1ec5"
            "\u00ec\u1ecb\u1ec9\u0129\u00ed\u00f2\u1ecd\u1ecf\u00f5"
            "\u00f3\u00f4\u1ed3\u1ed1\u1ed9\u1ed5\u1ed7\u01a1\u1edd"
            "\u1edb\u1ee3\u1edf\u1ee1\u00f9\u1ee5\u1ee7\u0169\u00fa"
            "\u01b0\u1eeb\u1ee9\u1ef1\u1eed\u1eef\u1ef3\u1ef5\u1ef7"
            "\u1ef9\u00fd\u0111]",
            text.lower(),
        )
    )


def _detect_romance_language(tokens: List[str]) -> str | None:
    if detect_langs is None or len(tokens) < 4:
        return None

    try:
        candidates = detect_langs(" ".join(tokens))
    except LangDetectException:
        return None

    if not candidates:
        return None

    best = candidates[0]
    best_lang = normalize_translation_lang(best.lang)

    if best_lang not in ROMANCE_LANGDETECT_CODES:
        return None

    if float(best.prob) < 0.72:
        return None

    return best_lang


def detect_caption_language(text: str, fallback: str = "en") -> str:
    value = str(text or "").strip()

    if not value:
        return normalize_translation_lang(fallback)

    lowered = value.lower()

    scripted_language = _has_non_english_script(value)
    if scripted_language:
        return scripted_language

    if _has_vietnamese_diacritic(value):
        return "vi"

    if re.search(r"[\u00e1\u00e9\u00ed\u00f3\u00fa\u00f1\u00bf\u00a1]", lowered):
        return "es"

    if re.search(r"[\u00e3\u00f5\u00e7\u00ea\u00f4]", lowered):
        return "pt"

    tokens = _tokenize_for_language(value)

    if re.search(r"\b\d+\s*yo\b", lowered):
        tokens = [token for token in tokens if token != "yo"]

    meaningful_tokens = [
        token
        for token in tokens
        if token not in IGNORED_TOKENS
        and token not in MEME_LABELS
        and len(token) >= 3
    ]

    language_tokens = [
        token
        for token in tokens
        if token not in {"pov"}
        and token not in MEME_LABELS
        and len(token) >= 2
    ]

    if not meaningful_tokens:
        return normalize_translation_lang(fallback)

    token_set = set(meaningful_tokens)
    spanish_strong_count = len(token_set & SPANISH_STRONG_MARKERS)
    spanish_context_count = len(token_set & SPANISH_CONTEXT_MARKERS)
    portuguese_count = len(token_set & PORTUGUESE_MARKERS)
    french_count = len(token_set & FRENCH_STRONG_MARKERS)
    english_count = sum(1 for token in meaningful_tokens if token in ENGLISH_WORDS)
    english_ratio = english_count / max(1, len(meaningful_tokens))
    spanish_score = (spanish_strong_count * 2) + spanish_context_count
    romance_language = _detect_romance_language(language_tokens)

    if spanish_strong_count:
        return "es"

    if portuguese_count >= 1 and portuguese_count + spanish_context_count >= 2:
        return "pt"

    if french_count >= 2:
        return "fr"

    if romance_language and english_ratio < 0.55:
        return romance_language

    if len(meaningful_tokens) <= 2:
        if french_count >= 1:
            return "fr"
        if spanish_context_count >= 1 and english_count == 0:
            return "es"
        return "en"

    if english_count == 0 and spanish_score >= 3:
        return "es"

    if spanish_score >= 4 and english_ratio < 0.65:
        return "es"

    return "en"


def is_english_caption(text: str, fallback: str = "en") -> bool:
    return detect_caption_language(text=text, fallback=fallback) == "en"


def find_non_english_adjacent_pair(text: str) -> str | None:
    value = str(text or "").strip()

    if not value:
        return None

    if not is_english_caption(value, fallback="en"):
        return value

    tokens = _tokenize_for_language(value)
    tokens = [
        token
        for token in tokens
        if token not in {"pov"}
        and token not in MEME_LABELS
        and len(token) >= 2
    ]

    if len(tokens) < 2:
        return None

    for index in range(len(tokens) - 1):
        pair = f"{tokens[index]} {tokens[index + 1]}"

        if not is_english_caption(pair, fallback="en"):
            return pair

    return None
