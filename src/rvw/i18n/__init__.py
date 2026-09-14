"""Strict translation lookup for all human-facing presentation chrome."""

from __future__ import annotations

from string import Formatter
from typing import Literal

from rvw.i18n.catalog_en import CATALOG as EN
from rvw.i18n.catalog_ko import CATALOG as KO

Locale = Literal["ko", "en"]
CATALOGS = {"en": EN, "ko": KO}
INFO_REESCALATION_TOKENS = {
    locale: tuple(CATALOGS[locale]["synthesis.info_reescalation_tokens"].split("|"))
    for locale in CATALOGS
}


def info_reescalation_tokens(locale: str) -> tuple[str, ...]:
    """Return closed locale-specific action vocabulary for informational findings."""

    if locale not in INFO_REESCALATION_TOKENS:
        raise ValueError(f"unsupported locale: {locale}")
    return INFO_REESCALATION_TOKENS[locale]


FORMAT_ARGUMENTS = {
    key: tuple(name for _, name, _, _ in Formatter().parse(template) if name)
    for key, template in EN.items()
}


def t(key: str, locale: str, **kwargs: object) -> str:
    """Format an exact catalog key; never silently fall back across locales."""
    if locale not in CATALOGS:
        raise ValueError(f"unsupported locale: {locale}")
    return CATALOGS[locale][key].format(**kwargs)


__all__ = ["FORMAT_ARGUMENTS", "Locale", "info_reescalation_tokens", "t"]
