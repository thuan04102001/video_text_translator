from typing import Dict, List, Optional

from core.translation.argos_translator import ArgosTranslator
from core.translation.base_translator import BaseTranslator


SUPPORTED_TRANSLATION_ENGINES = {
    "argos",
}


class TranslatorRouter:
    """
    Central translation router.

    Nhiệm vụ:
    - chọn translation engine
    - kiểm tra engine có available không
    - translate single/batch
    - là điểm duy nhất render_service gọi để dịch caption

    Sau này sẽ mở rộng:
    - gemini
    - openrouter
    - gpt
    """

    def __init__(self) -> None:
        self._engines = {
            "argos": ArgosTranslator(),
        }

    def get_engine(
        self,
        engine_name: str = "argos",
    ) -> BaseTranslator:
        normalized_name = str(engine_name or "argos").strip().lower()

        if normalized_name not in SUPPORTED_TRANSLATION_ENGINES:
            raise ValueError(
                f"Translation engine không hỗ trợ: {engine_name}. "
                f"Supported: {sorted(SUPPORTED_TRANSLATION_ENGINES)}"
            )

        engine = self._engines.get(normalized_name)

        if engine is None:
            raise RuntimeError(
                f"Translation engine chưa được khởi tạo: {normalized_name}"
            )

        return engine

    def is_available(
        self,
        engine_name: str = "argos",
    ) -> bool:
        engine = self.get_engine(engine_name)

        return engine.is_available()

    def translate_text(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "vi",
        engine_name: str = "argos",
        options: Optional[Dict] = None,
    ) -> str:
        engine = self.get_engine(engine_name)

        if not engine.is_available():
            raise RuntimeError(
                f"Translation engine chưa sẵn sàng: {engine_name}"
            )

        return engine.translate_text(
            text=text,
            source_lang=source_lang,
            target_lang=target_lang,
            options=options,
        )

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str = "en",
        target_lang: str = "vi",
        engine_name: str = "argos",
        options: Optional[Dict] = None,
    ) -> List[str]:
        engine = self.get_engine(engine_name)

        if not engine.is_available():
            raise RuntimeError(
                f"Translation engine chưa sẵn sàng: {engine_name}"
            )

        clean_texts = [
            str(text or "").strip()
            for text in texts
        ]

        if not clean_texts:
            return []

        return engine.translate_batch(
            texts=clean_texts,
            source_lang=source_lang,
            target_lang=target_lang,
            options=options,
        )


translator_router = TranslatorRouter()


def translate_text(
    text: str,
    source_lang: str = "en",
    target_lang: str = "vi",
    engine_name: str = "argos",
    options: Optional[Dict] = None,
) -> str:
    return translator_router.translate_text(
        text=text,
        source_lang=source_lang,
        target_lang=target_lang,
        engine_name=engine_name,
        options=options,
    )


def translate_batch(
    texts: List[str],
    source_lang: str = "en",
    target_lang: str = "vi",
    engine_name: str = "argos",
    options: Optional[Dict] = None,
) -> List[str]:
    return translator_router.translate_batch(
        texts=texts,
        source_lang=source_lang,
        target_lang=target_lang,
        engine_name=engine_name,
        options=options,
    )


def is_translation_available(
    engine_name: str = "argos",
) -> bool:
    return translator_router.is_available(
        engine_name=engine_name,
    )