import re

_GO_EMBED_RE = re.compile(r'^\s*//go:embed\b', re.MULTILINE)

# C/C++: block absolute AND relative traversal includes
_C_ABS_INCLUDE_RE = re.compile(r'#include\s*"/', re.MULTILINE)
_C_TRAVERSAL_INCLUDE_RE = re.compile(r'#include\s*"[^"]*\.\.[^"]*"', re.MULTILINE)

# Rust: block file-reading macros (absolute + relative) and env exfiltration.
# env!("VAR") reads environment variables at COMPILE TIME -- leaks INTERNAL_TOKEN.
_RUST_ABS_INCLUDE_RE = re.compile(r'include_(?:bytes|str)!\s*\(\s*"/', re.MULTILINE)
_RUST_TRAVERSAL_INCLUDE_RE = re.compile(r'include_(?:bytes|str|)!\s*\(\s*"[^"]*\.\.[^"]*"', re.MULTILINE)
_RUST_ENV_RE = re.compile(r'(?:env|option_env)!\s*\(', re.MULTILINE)

_C_FAMILY_IDS = frozenset({"c", "cpp", "cpp11", "cpp14", "cpp17", "cpp20", "cpp23"})


def validate_source(language_id: str, source_code: str) -> str | None:
    """Return error message if source is rejected, None if OK."""
    if language_id == "go":
        if _GO_EMBED_RE.search(source_code):
            return "CompileError: //go:embed directive is not allowed"

    if language_id in _C_FAMILY_IDS:
        if _C_ABS_INCLUDE_RE.search(source_code):
            return "CompileError: absolute path #include is not allowed"
        if _C_TRAVERSAL_INCLUDE_RE.search(source_code):
            return "CompileError: path traversal in #include is not allowed"

    if language_id == "rust":
        if _RUST_ABS_INCLUDE_RE.search(source_code):
            return "CompileError: include_bytes!/include_str! with absolute path is not allowed"
        if _RUST_TRAVERSAL_INCLUDE_RE.search(source_code):
            return "CompileError: path traversal in include macro is not allowed"
        if _RUST_ENV_RE.search(source_code):
            return "CompileError: env!/option_env! macros are not allowed"

    return None
