import re
import unicodedata
from typing import Dict, List, Optional

from core.translation.meme_translation_memory import normalize_memory_key


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text or ""))

    return "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )


def compact_semantic_key(text: str) -> str:
    value = strip_accents(normalize_memory_key(text))
    value = value.replace("ñ", "n")
    value = re.sub(r"[^a-z0-9]+", " ", value)

    return re.sub(r"\s+", " ", value).strip()


def clean_outer_quotes(text: str) -> str:
    return str(text or "").strip().strip("\"'“”")


def preserve_wrapping_quotes(original_text: str, translated_text: str) -> str:
    stripped = str(original_text or "").strip()
    translated = str(translated_text or "").strip()

    if not translated:
        return translated

    if stripped.startswith('"') and not translated.startswith('"'):
        translated = f'"{translated}'

    if stripped.endswith('"') and not translated.endswith('"'):
        translated = f'{translated}"'

    return translated


def translate_label(text: str) -> Optional[str]:
    key = normalize_memory_key(text).rstrip(":")

    labels = {
        "me": "Tôi",
        "mom": "Mẹ",
        "dad": "Bố",
        "bro": "Anh bạn",
        "son": "Con trai",
        "girl": "Cô gái",
        "boy": "Chàng trai",
        "girls": "Các cô gái",
        "boys": "Các cậu con trai",
        "teacher": "Giáo viên",
        "chatgpt": "ChatGPT",
        "chicas": "Các cô gái",
        "chicos": "Các chàng trai",
        "ninos": "Các học sinh",
        "niños": "Các học sinh",
        "mama": "Mẹ",
        "mamá": "Mẹ",
        "papa": "Bố",
        "papá": "Bố",
        "padres": "Bố mẹ",
        "yo": "Tôi",
        "in movies": "Trong phim",
        "in the movies": "Trong phim",
        "in the movies:": "Trong phim:",
        "in movie": "Trong phim",
        "in moves": "Trong phim",
        "in moves?": "Trong phim",
        "inthe moves": "Trong phim",
        "inthe moves?": "Trong phim",
        "inthe movies": "Trong phim",
        "inthe movies?": "Trong phim",
        "in reality": "Ngoài đời",
        "in reality;": "Ngoài đời:",
        "falling": "Bị rơi",
    }

    if key in labels:
        suffix = ":" if str(text or "").strip().endswith(":") else ""
        return f"{labels[key]}{suffix}"

    return None


def split_label_and_body(text: str) -> Optional[tuple]:
    raw = clean_outer_quotes(text)
    match = re.match(r"^\s*([A-Za-z][A-Za-z ]{0,24})\s*:\s*(.+)$", raw)

    if not match:
        return None

    label = match.group(1).strip()
    body = match.group(2).strip()
    translated_label = translate_label(f"{label}:")

    if not translated_label or not body:
        return None

    return translated_label, body


def translate_label_with_body(text: str) -> Optional[str]:
    split_result = split_label_and_body(text)

    if not split_result:
        return None

    translated_label, body = split_result
    translated_body = translate_clause(body)

    if not translated_body:
        return None

    return f"{translated_label} {translated_body}"


def translate_common_phrase(text: str) -> Optional[str]:
    key = normalize_memory_key(text).strip("*~ ")

    if key.startswith("cthen "):
        key = key[1:]

    phrase_map = {
        "help me mom": "Mẹ ơi cứu con với",
        "mom help me": "Mẹ ơi cứu con với",
        "i feel sick": "Con thấy không khỏe",
        "feel sick": "Con thấy không khỏe",
        "you know why": "Con biết vì sao không?",
        "because you're always on your phone": "Vì con lúc nào cũng dán mắt vào điện thoại",
        "forgot my umbrella": "Con quên mang ô rồi",
        "finding what to buy": "Tìm xem nên mua gì",
        "cant think of any": "Không nghĩ ra mua gì cả",
        "can't think of any": "Không nghĩ ra mua gì cả",
        "where did i put it": "Mình để nó đâu rồi?",
        "where did i put": "Mình để nó đâu rồi?",
        "where's my phone": "Điện thoại của mình đâu rồi?",
        "where is my phone": "Điện thoại của mình đâu rồi?",
        "i can't find my phone": "Con không tìm thấy điện thoại",
        "i cant find my phone": "Con không tìm thấy điện thoại",
        "not in my bed": "Không ở trên giường",
        "then whose phone are you holding": "Vậy con đang cầm điện thoại của ai?",
        "then whose phone are you holding?": "Vậy con đang cầm điện thoại của ai?",
        "only in thailand": "Chỉ có ở Thái Lan",
        "in movies": "Trong phim",
        "in reality": "Ngoài đời",
        "falling": "Bị rơi",
        "falling:": "Bị rơi:",
        "vida para hombre": "Cuộc đời đàn ông",
        "life for men": "Cuộc đời đàn ông",
        "ninos de la clase a": "Học sinh lớp A",
        "niños de la clase a": "Học sinh lớp A",
        "ninos de la clase b": "Học sinh lớp B",
        "niños de la clase b": "Học sinh lớp B",
        "llamemos un taxi": "Gọi taxi đi",
    }

    return phrase_map.get(key)


def translate_noun_phrase(text: str) -> Optional[str]:
    key = normalize_memory_key(text)

    noun_map = {
        "a random song": "một bài hát ngẫu nhiên",
        "random song": "một bài hát ngẫu nhiên",
        "a song": "một bài hát",
        "your head": "trong đầu bạn",
        "my head": "trong đầu tôi",
        "the store": "cửa hàng",
        "the beach": "bãi biển",
        "your phone": "điện thoại của con",
        "my umbrella": "ô của con",
    }

    return noun_map.get(key)


def translate_place_name(text: str) -> str:
    clean_text = str(text or "").strip().strip(".!?")
    place_map = {
        "new york": "New York",
        "usa": "Mỹ",
        "america": "Mỹ",
        "greece": "Hy Lạp",
        "europe": "châu Âu",
        "asia": "châu Á",
        "thailand": "Thái Lan",
        "pattaya": "Pattaya",
    }

    return place_map.get(normalize_memory_key(clean_text), clean_text)


def translate_actor_phrase(text: str) -> Optional[str]:
    key = normalize_memory_key(text)

    actor_map = {
        "dad lion": "bố sư tử",
        "lion dad": "bố sư tử",
        "his cub": "con mình",
        "his son": "con trai mình",
        "son": "con trai",
        "cub": "sư tử con",
    }

    return actor_map.get(key)


def translate_action_phrase(text: str) -> Optional[str]:
    key = normalize_memory_key(text)

    action_map = {
        "roar": "gầm",
        "rear": "nuôi con",
        "raise": "nuôi con",
    }

    return action_map.get(key)


def translate_clause(text: str) -> Optional[str]:
    raw = clean_outer_quotes(text)
    key = normalize_memory_key(raw)
    compact_key = compact_semantic_key(raw)

    common = translate_common_phrase(raw)

    if common:
        return common

    if key in {
        "singing a random song in your head",
        "singing random song in your head",
    }:
        return "trong đầu bạn tự nhiên vang lên một bài hát"

    if key in {
        "you're singing a random song in your head",
        "you are singing a random song in your head",
    }:
        return "trong đầu bạn tự nhiên vang lên một bài hát"

    if key == "leaving the store without buying anything":
        return "rời khỏi cửa hàng mà không mua gì"

    if key == "you leave the store without buying anything":
        return "bạn rời khỏi cửa hàng mà không mua gì"

    if key == "your mom tells you the reason you're sick":
        return "mẹ bạn nói lý do bạn bị ốm"

    if key == "your mom spots a friend she hasn't seen since 1945":
        return "mẹ bạn phát hiện một người bạn mà bà ấy chưa gặp từ năm 1945"

    if key == "what it feels like leaving the store without buying anything":
        return "cảm giác khi rời khỏi cửa hàng mà không mua gì"

    if key in {
        "looking for something you're already holding",
        "looking for something youre already holding",
    }:
        return "tìm thứ bạn đang cầm sẵn"

    if key in {
        "he's going to",
        "hes going to",
        "he is going to",
    }:
        return "nó sẽ"

    if key in {"be a doctor", "a doctor"}:
        return "làm bác sĩ"

    if key in {"be a lawyer", "be a laywer", "a lawyer", "a laywer"}:
        return "làm luật sư"

    if (
        ("no he s going to be a lawyer" in compact_key)
        or ("no hes going to be a lawyer" in compact_key)
        or ("no he s going to be a laywer" in compact_key)
        or ("no hes going to be a laywer" in compact_key)
    ):
        return "không, nó sẽ làm luật sư"

    if "he s going to be a doctor" in compact_key or "hes going to be a doctor" in compact_key:
        return "nó sẽ làm bác sĩ"

    if (
        "he s going to be a lawyer" in compact_key
        or "hes going to be a lawyer" in compact_key
        or "he s going to be a laywer" in compact_key
        or "hes going to be a laywer" in compact_key
    ):
        return "nó sẽ làm luật sư"

    if (
        ("dad no" in compact_key or "dad nope" in compact_key)
        and ("lawyer" in compact_key or "laywer" in compact_key)
    ):
        return "Bố: không, nó sẽ làm luật sư"

    if (
        "mama fue" in compact_key
        and "tienda" in compact_key
        and "dejo solo" in compact_key
        and "papa" in compact_key
    ):
        return "POV: mẹ đi cửa hàng và để bạn ở nhà một mình với bố"

    if (
        "mama fue" in compact_key
        and "tienda pov" in compact_key
        and "y te dejo" in compact_key
        and "papa" in compact_key
    ):
        return "POV: mẹ đi cửa hàng và để bạn ở nhà một mình với bố"

    if (
        "mama fue a la tienda" in compact_key
        and "y te dejo solo con papa" in compact_key
    ):
        return "POV: mẹ đi cửa hàng và để bạn ở nhà một mình với bố"

    if (
        "babies" in key
        and "world" in key
        and "mama" in key
        and "china" in key
    ):
        return 'Em bé khắp thế giới nói "mama" rất dễ, còn em bé ở Trung Quốc thì cố nói "妈咪妈咪"'

    if "mom" in key and ("trying to figure out why" in key or "tryna figure out why" in key):
        if "sick" in key:
            return "Mẹ đang cố tìm hiểu vì sao tôi bị bệnh"

        return "Mẹ đang cố tìm hiểu vì sao tôi bị bệnh"

    if key in {"why i got sick", "why i got sick:"}:
        return "vì sao tôi bị bệnh"

    if key in {
        "what does a fall look like",
        "what does a fall look like:",
        "what does falling look like",
        "what does falling look like:",
        "what falling looks like",
        "what falling looks like:",
    }:
        return "Bị rơi trông như thế nào:"

    if "asked my bro" in key and "girlfriend" in key and "$200" in key:
        return "Tôi nhờ anh bạn và bạn gái gửi cho tôi $200"

    if "my girlfriend sends" in key and "bro sends" in key:
        match_girl = re.search(r"girlfriend sends:?\s*\$?([\d,.]+)", key)
        match_bro = re.search(r"bro sends:?\s*\$?([\d,.]+)", key)

        if match_girl and match_bro:
            return (
                f"Bạn gái gửi: ${match_girl.group(1)}, "
                f"anh bạn gửi: ${match_bro.group(1)}"
            )

        return "Bạn gái gửi tiền, anh bạn cũng gửi tiền"

    if (
        "mom sends my old clothes" in key
        and "grandparents" in key
        and "village" in key
        and "fishing" in key
    ):
        return "Mẹ gửi quần áo cũ của tôi cho ông bà ở quê. Hôm sau, ông ngoại mặc đi câu:"

    match = re.fullmatch(r"only in (.+)", key)

    if match:
        place = translate_place_name(match.group(1))
        return f"chỉ có ở {place}"

    match = re.search(r"\bonly in ([a-z ]+)", key)

    if match:
        raw_place = match.group(1).strip()
        raw_place = re.split(r"\s+(walking|street|welcome|pattaya)\b", raw_place)[0].strip()

        if raw_place:
            place = translate_place_name(raw_place)
            return f"chỉ có ở {place}"

    match = re.fullmatch(r"(ninos|niños) de la clase ['\"]?([a-z])['\"]?\s*=?", key)

    if match:
        return f"Học sinh lớp {match.group(2).upper()}"

    match = re.fullmatch(r"(chicas|chicos)\s*:\s*(.+)", key)

    if match:
        label = translate_label(match.group(1) + ":") or match.group(1)
        body = translate_clause(match.group(2)) or translate_common_phrase(match.group(2))

        if body:
            return f"{label} {body}"

    match = re.fullmatch(r"(.+?)\s+llamemos un taxi", key)

    if match:
        prefix = translate_clause(match.group(1))

        if prefix:
            return f"{prefix}. Gọi taxi đi"

        return "Gọi taxi đi"

    if "llamemos un taxi" in key or "llamemos un taxil" in key:
        if "200" in key and "metro" in key:
            return "mới 200 mét thôi, gọi taxi đi"

        return "Gọi taxi đi"

    if "taxi" in compact_key and "200" in compact_key and "metro" in compact_key:
        return "mới 200 mét thôi, gọi taxi đi"

    if (
        ("chicas" in compact_key or "chicos" in compact_key)
        and "200" in compact_key
        and "metro" in compact_key
        and "taxi" in compact_key
    ):
        label = "Các cô gái" if "chicas" in compact_key else "Các chàng trai"
        return f"{label}: mới 200 mét thôi, gọi taxi đi"

    if key.startswith("in reality"):
        return "Ngoài đời"

    if (
        key.startswith("in movies")
        or key.startswith("in the movies")
        or key.startswith("in movie")
        or key.startswith("in moves")
        or key.startswith("inthe movies")
        or key.startswith("inthe moves")
    ):
        return "Trong phim"

    if key == "we went to the beach last month":
        return "tháng trước tụi con đi biển"

    if key == "so have you traveled anywhere recently":
        return "dạo này bạn có đi đâu không?"

    if re.fullmatch(r"lion dad teaches his son to rear:?", key):
        return "bố sư tử dạy con trai cách nuôi con"

    if re.fullmatch(r"lion dad teaches his cub to rear:?", key):
        return "bố sư tử dạy con cách nuôi con"

    match = re.fullmatch(r"(.+?)\s+teaches\s+(.+?)\s+to\s+(.+)", key)

    if match:
        teacher = translate_actor_phrase(match.group(1))
        learner = translate_actor_phrase(match.group(2))
        action = translate_action_phrase(match.group(3))

        if teacher and learner and action:
            return f"{teacher} dạy {learner} cách {action}"

    match = re.fullmatch(r"(.+?)\s+teaching\s+(.+?)\s+how to\s+(.+)", key)

    if match:
        teacher = translate_actor_phrase(match.group(1))
        learner = translate_actor_phrase(match.group(2))
        action = translate_action_phrase(match.group(3))

        if teacher and learner and action:
            return f"{teacher} dạy {learner} cách {action}"

    if all(token in key for token in {"dad", "lion", "cub", "roar"}):
        return "bố sư tử dạy con cách gầm"

    if (
        all(token in key for token in {"lion", "dad", "son"})
        and "teach" not in key
        and "rear" not in key
    ):
        return "bố sư tử và con trai"

    match = re.fullmatch(r"tomorrow\s+(we|we'll|we will)\s+go to\s+(.+)", key)

    if match:
        place = translate_place_name(match.group(2))
        return f"ngày mai chúng ta sẽ đi {place}"

    match = re.fullmatch(r"(we|we'll|we will)\s+go to\s+(.+)\s+tomorrow", key)

    if match:
        place = translate_place_name(match.group(2))
        return f"ngày mai chúng ta sẽ đi {place}"

    match = re.fullmatch(r"tomorrow\s+(you|you'll|you will)\s+go to\s+(.+)", key)

    if match:
        place = translate_place_name(match.group(2))
        return f"ngày mai bạn sẽ đi {place}"

    match = re.fullmatch(r"(.+?) without (.+)", key)

    if match:
        action = translate_clause(match.group(1))
        object_text = translate_noun_phrase(match.group(2))

        if action and object_text:
            return f"{action} mà không {object_text}"

    return None


def translate_pov_text(text: str) -> Optional[str]:
    raw = clean_outer_quotes(text)
    match = re.match(r"^\s*pov\s*:\s*(.+)$", raw, flags=re.IGNORECASE)

    if not match:
        return None

    body = match.group(1).strip()
    body_key = normalize_memory_key(body)

    if body_key.startswith("when you're "):
        body = body[12:].strip()
        translated = translate_clause(body)

        if translated:
            if translated.startswith("khi "):
                return f"POV: {translated}"

            return f"POV: khi {translated}"

    if body_key.startswith("when you are "):
        body = body[13:].strip()
        translated = translate_clause(body)

        if translated:
            if translated.startswith("khi "):
                return f"POV: {translated}"

            return f"POV: khi {translated}"

    if body_key.startswith("what it feels like "):
        translated = translate_clause(body)

        if translated:
            return f"POV: {translated}"

    translated = translate_clause(body)

    if translated:
        return f"POV: {translated}"

    return None


def semantic_translate_before_argos(
    text: str,
    caption_role: str = "",
    context: Optional[Dict] = None,
) -> Optional[str]:
    label_with_body = translate_label_with_body(text)

    if label_with_body:
        return preserve_wrapping_quotes(text, label_with_body)

    label = translate_label(text)

    if label:
        return label

    pov_translation = translate_pov_text(text)

    if pov_translation:
        return preserve_wrapping_quotes(text, pov_translation)

    common = translate_common_phrase(text)

    if common:
        return preserve_wrapping_quotes(text, common)

    clause = translate_clause(text)

    if clause:
        return preserve_wrapping_quotes(text, clause)

    return None


def has_bad_argos_artifacts(text: str) -> bool:
    lowered = normalize_memory_key(text)
    bad_tokens = {
        "rundo",
        "youlre",
        "phonew",
        "goshi",
        "bệnh hoạn",
        "do rundo",
    }

    return any(token in lowered for token in bad_tokens)


def has_untranslated_english_fragment(text: str) -> bool:
    lowered = normalize_memory_key(text)
    english_markers = {
        " why ",
        " what ",
        " when ",
        " where ",
        " sick",
        " mom ",
        " dad ",
        " baby ",
        " girlfriend",
        " bro ",
        " sends",
        " asked",
        " trying",
        " going",
        " doctor",
        " lawyer",
        " laywer",
        " china",
        " babies",
        " world",
    }

    padded = f" {lowered} "

    return any(marker in padded for marker in english_markers)


def rewrite_after_argos(
    original_text: str,
    normalized_text: str,
    translated_text: str,
    caption_role: str = "",
    context: Optional[Dict] = None,
) -> str:
    semantic = semantic_translate_before_argos(
        text=normalized_text or original_text,
        caption_role=caption_role,
        context=context,
    )

    translated = str(translated_text or "").strip()

    if semantic and (
        not translated
        or has_bad_argos_artifacts(translated)
        or has_untranslated_english_fragment(translated)
    ):
        return semantic

    if semantic and caption_role == "MAIN_CAPTION_TEXT":
        return semantic

    if semantic and len(translated) > len(semantic) * 1.8:
        return semantic

    replacements = {
        "bệnh hoạn": "không khỏe",
        "điện thoại của bạn": "điện thoại của con",
        "do rundo": "ngẫu nhiên",
    }

    for source, target in replacements.items():
        translated = translated.replace(source, target)

    return translated


def build_translation_context(
    timelines: List[Dict],
    slot_index: int,
) -> Dict:
    current = timelines[slot_index] if 0 <= slot_index < len(timelines) else {}
    previous_item = timelines[slot_index - 1] if slot_index > 0 else {}
    next_item = timelines[slot_index + 1] if slot_index + 1 < len(timelines) else {}
    main_caption = ""

    for timeline in timelines:
        if timeline.get("caption_role") == "MAIN_CAPTION_TEXT":
            main_caption = str(timeline.get("text") or "").strip()
            break

    return {
        "caption_role": current.get("caption_role") or "",
        "main_caption": main_caption,
        "previous_text": previous_item.get("text") or "",
        "next_text": next_item.get("text") or "",
    }
