import pytest
from app.languages.config import LANGUAGES, LanguageConfig, get_language, get_all_languages

REQUIRED_FIELDS = {"id", "name", "version", "source_file", "run_cmd"}


class TestLanguageConfigs:
    @pytest.mark.parametrize("lang_id", [
        k for k, v in LANGUAGES.items() if id(v) == id(LANGUAGES[k])
    ])
    def test_required_fields_present(self, lang_id):
        cfg = LANGUAGES[lang_id]
        for field in REQUIRED_FIELDS:
            assert getattr(cfg, field), f"{lang_id} missing {field}"

    @pytest.mark.parametrize("lang_id", list(LANGUAGES.keys()))
    def test_no_image_field(self, lang_id):
        assert not hasattr(LANGUAGES[lang_id], "image")

    def test_compiled_languages_have_compile_cmd(self):
        for lang_id, cfg in LANGUAGES.items():
            if cfg.id in ("py3", "pypy3", "js", "ruby"):
                assert cfg.compile_cmd is None
            elif cfg.id not in ("py3", "pypy3", "js", "ruby"):
                if LANGUAGES.get(lang_id) is cfg and cfg.compile_cmd is not None:
                    assert isinstance(cfg.compile_cmd, list)


class TestGetLanguage:
    def test_known_language(self):
        assert get_language("cpp") is not None
        assert get_language("cpp").id == "cpp"

    def test_unknown_language(self):
        assert get_language("brainfuck") is None


class TestAliases:
    def test_cpp17_is_cpp(self):
        assert get_language("cpp17") is get_language("cpp")

    def test_py_is_py3(self):
        assert get_language("py") is get_language("py3")

    def test_alias_same_object(self):
        assert LANGUAGES["cpp17"] is LANGUAGES["cpp"]
        assert LANGUAGES["py"] is LANGUAGES["py3"]


class TestGetAllLanguages:
    def test_no_duplicates(self):
        all_langs = get_all_languages()
        ids = [cfg.id for cfg in all_langs]
        assert len(ids) == len(set(ids))

    def test_fewer_than_dict_keys(self):
        assert len(get_all_languages()) < len(LANGUAGES)

    def test_contains_canonical_entries(self):
        all_ids = {cfg.id for cfg in get_all_languages()}
        assert "cpp" in all_ids
        assert "py3" in all_ids
