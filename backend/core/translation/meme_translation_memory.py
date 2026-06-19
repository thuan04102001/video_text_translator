import json
import os
import re
import threading
from datetime import datetime
from typing import Dict, Optional


MEMORY_PATH = os.path.join(
    os.path.dirname(__file__),
    "meme_translation_memory.json",
)

_MEMORY_LOCK = threading.Lock()


def normalize_memory_key(text: str) -> str:
    value = str(text or "").strip().lower()
    value = value.replace("’", "'").replace("`", "'").replace("´", "'")
    value = re.sub(r"[“”]", '"', value)
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" \t\r\n\"'")
    value = re.sub(r"\s+([?.!,;:])", r"\1", value)

    return value


def load_memory() -> Dict:
    if not os.path.isfile(MEMORY_PATH):
        return {
            "version": 1,
            "ocr_repairs": {},
            "phrase_translations": {},
            "pending_cases": [],
        }

    with open(MEMORY_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def save_memory(memory: Dict) -> None:
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)

    temp_path = f"{MEMORY_PATH}.tmp"

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(memory, file, ensure_ascii=False, indent=2)
        file.write("\n")

    os.replace(temp_path, MEMORY_PATH)


def repair_ocr_text(text: str, memory: Optional[Dict] = None) -> str:
    if memory is None:
        memory = load_memory()

    repaired = str(text or "").strip()

    if not repaired:
        return repaired

    repaired = repaired.replace("’", "'").replace("`", "'").replace("´", "'")
    repaired = repaired.replace("“", '"').replace("”", '"')

    cjk_chars = re.findall(r"[\u4e00-\u9fff]", repaired)
    latin_chars = re.findall(r"[A-Za-z]", repaired)

    if 0 < len(cjk_chars) <= 1 and len(latin_chars) >= 6:
        repaired = re.sub(r"\s*[\u4e00-\u9fff]\s*", " ", repaired)

    repaired = re.sub(
        r"(?<![A-Za-z])S(?=\d)",
        "$",
        repaired,
    )

    repairs = memory.get("ocr_repairs", {}) or {}

    for source, target in repairs.items():
        repaired = re.sub(
            rf"\b{re.escape(source)}\b",
            str(target),
            repaired,
            flags=re.IGNORECASE,
        )

    repaired = re.sub(r"\byou\s*lre\b", "you're", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\byou\s*1re\b", "you're", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bbbed\b", "bed", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bcThen\b", "Then", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"^[cC](Then\b)", r"\1", repaired)
    repaired = re.sub(r"\bIve\b", "I've", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bIm\b", "I'm", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bits\b", "it's", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bThats\b", "That's", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bALA\b", "A LA", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bYTE\b", "Y TE", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bSOO\b", "SOLO", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bRARARA\b", "PAPA", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bFUENDA\b", "FUE A", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bMAMA\s+FUENDA\b", "MAMA FUE A", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\bMAM[ÁA]\s+FUE\s+ALLA\b", "MAMÁ FUE A LA", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\s+", " ", repaired).strip()

    repaired = re.sub(r"\s+([?.!,;:])", r"\1", repaired)

    return repaired.strip()


def get_approved_translation(
    text: str,
    memory: Optional[Dict] = None,
) -> Optional[str]:
    if memory is None:
        memory = load_memory()

    key = normalize_memory_key(text)
    translations = memory.get("phrase_translations", {}) or {}

    if key in translations:
        return str(translations[key]).strip()

    return None


def pending_case_exists(memory: Dict, key: str) -> bool:
    for case in memory.get("pending_cases", []) or []:
        if case.get("key") == key:
            return True

    return False


def remember_pending_case(
    original_text: str,
    normalized_text: str,
    translated_text: str,
    source_lang: str,
    target_lang: str,
    engine: str,
    caption_role: str = "",
) -> None:
    normalized_key = normalize_memory_key(normalized_text or original_text)

    if not normalized_key:
        return

    translated = str(translated_text or "").strip()

    if not translated:
        return

    with _MEMORY_LOCK:
        memory = load_memory()

        approved = memory.get("phrase_translations", {}) or {}

        if normalized_key in approved:
            return

        if pending_case_exists(memory, normalized_key):
            return

        pending_cases = memory.setdefault("pending_cases", [])
        pending_cases.append(
            {
                "key": normalized_key,
                "original_text": str(original_text or "").strip(),
                "normalized_text": str(normalized_text or "").strip(),
                "translated_text": translated,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "engine": engine,
                "caption_role": caption_role,
                "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "status": "pending_review",
            }
        )

        save_memory(memory)
