from __future__ import annotations

import re
from pathlib import Path
from string import Formatter

import pytest


def test_catalog_key_parity_and_declared_kwargs_format() -> None:
    from rvw.i18n import FORMAT_ARGUMENTS, t
    from rvw.i18n.catalog_en import CATALOG as en
    from rvw.i18n.catalog_ko import CATALOG as ko

    assert en.keys() == ko.keys() == FORMAT_ARGUMENTS.keys()
    for key in en:
        for locale, catalog in (("en", en), ("ko", ko)):
            declared = {name for _, name, _, _ in Formatter().parse(catalog[key]) if name}
            assert declared == set(FORMAT_ARGUMENTS[key])
            kwargs = {name: 12 for name in declared}
            assert t(key, locale, **kwargs) == catalog[key].format(**kwargs)


def test_translation_fails_closed_for_unknown_key_locale_or_missing_arguments() -> None:
    from rvw.i18n import t

    with pytest.raises(KeyError):
        t("missing.key", "en")
    with pytest.raises(ValueError):
        t("common.none", "fr")
    with pytest.raises(KeyError):
        t("report.reason", "en")


def test_renderer_modules_have_no_hangul_literals() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "rvw"
    for filename in ("report.py", "publish.py", "gate.py", "stack_report.py"):
        assert not re.search("[\uac00-\ud7a3]", (root / filename).read_text()), filename
