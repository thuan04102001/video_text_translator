from typing import Dict, List, Optional

from core.translation.base_translator import BaseTranslator
from core.translation.language_detector import normalize_translation_lang


class ArgosTranslator(BaseTranslator):
    """
    Argos offline translator.

    Supports direct translation when the language pair exists. If a direct
    pair is missing, it can translate through English, e.g. es -> en -> vi.
    Missing Argos packages are installed on demand unless disabled through
    options={"auto_install": False}.
    """

    engine_name = "argos"

    def __init__(self) -> None:
        self._argostranslate_translate = None
        self._load_argos()

    def _load_argos(self) -> None:
        try:
            from argostranslate import translate

            self._argostranslate_translate = translate
        except Exception:
            self._argostranslate_translate = None

    def is_available(self) -> bool:
        if self._argostranslate_translate is None:
            return False

        try:
            languages = self._argostranslate_translate.get_installed_languages()
            return len(languages) > 0
        except Exception:
            return False

    def _install_language_pair(self, source_lang: str, target_lang: str) -> bool:
        try:
            from argostranslate import package

            package.update_package_index()
            available_packages = package.get_available_packages()
            matched_package = next(
                (
                    item
                    for item in available_packages
                    if getattr(item, "from_code", "") == source_lang
                    and getattr(item, "to_code", "") == target_lang
                ),
                None,
            )

            if matched_package is None:
                return False

            package_path = matched_package.download()
            package.install_from_path(package_path)
            self._load_argos()

            return True
        except Exception:
            return False

    def _get_language(self, code: str):
        if self._argostranslate_translate is None:
            return None

        for language in self._argostranslate_translate.get_installed_languages():
            if getattr(language, "code", "") == code:
                return language

        return None

    def _find_language_pair(
        self,
        source_lang: str,
        target_lang: str,
        auto_install: bool = True,
    ):
        source_lang = normalize_translation_lang(source_lang)
        target_lang = normalize_translation_lang(target_lang)

        source_language = self._get_language(source_lang)
        target_language = self._get_language(target_lang)

        if (
            (source_language is None or target_language is None)
            and auto_install
            and self._install_language_pair(source_lang, target_lang)
        ):
            source_language = self._get_language(source_lang)
            target_language = self._get_language(target_lang)

        if source_language is None or target_language is None:
            return None

        try:
            translation = source_language.get_translation(target_language)

            if translation is not None:
                return translation

            if auto_install and self._install_language_pair(source_lang, target_lang):
                source_language = self._get_language(source_lang)
                target_language = self._get_language(target_lang)

                if source_language is not None and target_language is not None:
                    return source_language.get_translation(target_language)

            return None
        except Exception:
            return None

    def _translate_direct(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        auto_install: bool = True,
    ) -> Optional[str]:
        translation = self._find_language_pair(
            source_lang=source_lang,
            target_lang=target_lang,
            auto_install=auto_install,
        )

        if translation is None:
            return None

        return translation.translate(text)

    def translate_text(
        self,
        text: str,
        source_lang: str = "en",
        target_lang: str = "vi",
        options: Optional[Dict] = None,
    ) -> str:
        clean_text = str(text or "").strip()

        if not clean_text:
            return ""

        if self._argostranslate_translate is None:
            raise RuntimeError(
                "Argos Translate is not installed. Run: pip install argostranslate"
            )

        source_lang = normalize_translation_lang(source_lang)
        target_lang = normalize_translation_lang(target_lang)
        auto_install = bool((options or {}).get("auto_install", True))

        if source_lang == target_lang:
            return clean_text

        translated = self._translate_direct(
            text=clean_text,
            source_lang=source_lang,
            target_lang=target_lang,
            auto_install=auto_install,
        )

        if translated is not None:
            return translated

        if source_lang != "en" and target_lang != "en":
            english_text = self._translate_direct(
                text=clean_text,
                source_lang=source_lang,
                target_lang="en",
                auto_install=auto_install,
            )

            if english_text:
                translated = self._translate_direct(
                    text=english_text,
                    source_lang="en",
                    target_lang=target_lang,
                    auto_install=auto_install,
                )

                if translated:
                    return translated

        raise RuntimeError(
            f"Argos does not have a usable translation route: "
            f"{source_lang} -> {target_lang}."
        )

    def translate_batch(
        self,
        texts: List[str],
        source_lang: str = "en",
        target_lang: str = "vi",
        options: Optional[Dict] = None,
    ) -> List[str]:
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
