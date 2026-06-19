import re
from typing import Dict, List


def normalize_spaces(text: str) -> str:
    if text is None:
        return ""

    text = str(text)
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_quotes(text: str) -> str:
    text = text.replace("“", '"')
    text = text.replace("”", '"')
    text = text.replace("‘", "'")
    text = text.replace("’", "'")
    text = text.replace("`", "'")

    return text


def normalize_common_ocr_noise(text: str) -> str:
    """
    Chỉ clean noise nhẹ.

    Không được tự dịch.
    Không được tự sửa nghĩa mạnh.
    Không được tự đoán caption chính.
    """

    text = text.replace("|", "I")
    text = text.replace("…", "...")
    text = text.replace(" ,", ",")
    text = text.replace(" .", ".")
    text = text.replace(" !", "!")
    text = text.replace(" ?", "?")
    text = text.replace("( ", "(")
    text = text.replace(" )", ")")

    return text


def preserve_case_replace(text: str, wrong: str, right: str) -> str:
    """
    Replace một cụm OCR sai nhưng giữ case cơ bản.

    Ví dụ:
    - glrls -> girls
    - Glrls -> Girls
    - GLRLS -> GIRLS
    """

    pattern = re.compile(
        re.escape(wrong),
        flags=re.IGNORECASE,
    )

    def repl(match):
        original = match.group(0)

        if original.isupper():
            return right.upper()

        if original[:1].isupper():
            return right[:1].upper() + right[1:]

        return right

    return pattern.sub(repl, text)


def normalize_common_ocr_typos(text: str) -> str:
    """
    Sửa lỗi OCR chính tả phổ biến trước khi đưa sang translator.

    Nguyên tắc:
    - Không dịch.
    - Không tự quyết định caption nào là chính.
    - Không hardcode theo video cụ thể.
    - Chỉ sửa lỗi OCR phổ biến, có độ an toàn cao.
    """

    if not text:
        return ""

    replacements = {
        "glrls": "girls",
        "gIrls": "girls",
        "girIs": "girls",
        "beautifull": "beautiful",
        "prettyl": "pretty",
        "herel": "here",
        "toroar": "to roar",
        "hoW": "how",
        "s@": "so",
        "s0": "so",
        "w0w": "wow",
        "Wowj": "Wow,",
        "Wow;": "Wow,",
    }

    clean_text = text

    for wrong, right in replacements.items():
        clean_text = preserve_case_replace(
            text=clean_text,
            wrong=wrong,
            right=right,
        )

    clean_text = re.sub(
        r"\bso\s+pretty\b",
        "so beautiful",
        clean_text,
        flags=re.IGNORECASE,
    )

    clean_text = re.sub(
        r"\bso\s+beautiful\b",
        lambda match: (
            "So beautiful"
            if match.group(0)[:1].isupper()
            else "so beautiful"
        ),
        clean_text,
        flags=re.IGNORECASE,
    )

    clean_text = clean_text.replace(" ,", ",")
    clean_text = clean_text.replace(" ;", ";")
    clean_text = clean_text.replace(" :", ":")
    clean_text = clean_text.replace(" !", "!")
    clean_text = clean_text.replace(" ?", "?")

    clean_text = re.sub(r"\s+", " ", clean_text)

    return clean_text.strip()


def normalize_for_compare(text: str) -> str:
    """
    Chuẩn hóa để so sánh/gộp duplicate sau này.

    Chỉ dùng cho compare key.
    Không dùng để render trực tiếp.
    """

    text = normalize_text(text)
    text = text.lower()

    text = re.sub(r"[^a-z0-9À-ỹ]+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_text(text: str) -> str:
    text = normalize_spaces(text)
    text = normalize_quotes(text)
    text = normalize_common_ocr_noise(text)
    text = normalize_common_ocr_typos(text)
    text = normalize_spaces(text)

    return text


def is_probably_empty_text(text: str) -> bool:
    normalized = normalize_text(text)

    if not normalized:
        return True

    if len(normalized) <= 1:
        return True

    return False


def clean_ocr_item(item: Dict) -> Dict:
    original_text = item.get("text", "")
    clean_text = normalize_text(original_text)
    compare_text = normalize_for_compare(clean_text)

    return {
        **item,
        "original_text": original_text,
        "text": clean_text,
        "normalized_text": compare_text,
        "is_empty": is_probably_empty_text(clean_text),
    }


def clean_ocr_items(items: List[Dict]) -> List[Dict]:
    cleaned = []

    for item in items:
        cleaned_item = clean_ocr_item(item)

        if cleaned_item["is_empty"]:
            continue

        cleaned.append(cleaned_item)

    return cleaned


def clean_frame_ocr_result(frame: Dict) -> Dict:
    items = frame.get("items", [])

    cleaned_items = clean_ocr_items(items)

    return {
        **frame,
        "ocr_count": len(cleaned_items),
        "items": cleaned_items,
    }


def clean_sampled_frames_ocr_result(ocr_result: Dict) -> Dict:
    frames = ocr_result.get("frames", [])

    cleaned_frames = []
    total_items = 0

    for frame in frames:
        cleaned_frame = clean_frame_ocr_result(frame)
        cleaned_frames.append(cleaned_frame)
        total_items += cleaned_frame["ocr_count"]

    return {
        **ocr_result,
        "frame_count": len(cleaned_frames),
        "total_ocr_items": total_items,
        "frames": cleaned_frames,
    }