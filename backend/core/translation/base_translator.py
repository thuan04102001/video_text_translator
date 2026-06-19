from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class BaseTranslator(ABC):
    """
    Base class cho mọi translation engine.

    Mục tiêu:
    - mọi engine dùng chung interface
    - dễ thay Argos / Gemini / OpenRouter / GPT
    - hỗ trợ batch captions để tiết kiệm request/API credit
    """

    engine_name = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """
        Trả về True nếu engine có thể dùng được.
        Ví dụ:
        - Argos đã cài package/model
        - Gemini có API key
        - OpenRouter có API key
        - GPT có API key
        """
        raise NotImplementedError

    @abstractmethod
    def translate_text(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "vi",
        options: Optional[Dict] = None,
    ) -> str:
        """
        Dịch 1 đoạn text.
        """
        raise NotImplementedError

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str = "en",
        target_lang: str = "vi",
        options: Optional[Dict] = None,
    ) -> List[str]:
        """
        Default batch translate.

        Engine nào chưa có batch thật thì dùng fallback:
        translate từng câu một.

        Các engine API sau này có thể override function này để dùng:
        A<sep>B<sep>C
        """

        results = []

        for text in texts:
            translated = self.translate_text(
                text=text,
                source_lang=source_lang,
                target_lang=target_lang,
                options=options,
            )

            results.append(translated)

        return results