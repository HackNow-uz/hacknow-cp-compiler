import re

# ─────────────────────────────────────────────────────────────────────────
#  Go
# ─────────────────────────────────────────────────────────────────────────
_GO_EMBED_RE = re.compile(r'^\s*//go:embed\b', re.MULTILINE)


# ─────────────────────────────────────────────────────────────────────────
#  C / C++
#  Block any directive that can read host files at compile time.
# ─────────────────────────────────────────────────────────────────────────
# #include and #include_next, #embed (C23) with absolute or traversal paths
_C_DANGEROUS_INCLUDE_RE = re.compile(
    r'#\s*(?:include|include_next|embed)\s*[<"]\s*(?:/|[^>"]*\.\.)[^>"]*[>"]',
    re.MULTILINE,
)
# __has_include / __has_include_next probes — leak file existence via #error
_C_HAS_INCLUDE_RE = re.compile(
    r'\b__has_include(?:_next)?\s*\(\s*[<"]\s*(?:/|[^>"]*\.\.)',
    re.MULTILINE,
)
# Indirect #include FOO (macro-expanded path) — bypass for any literal regex
_C_INCLUDE_INDIRECT_RE = re.compile(
    r'#\s*include(?:_next)?\s+(?![<"])',
    re.MULTILINE,
)


# ─────────────────────────────────────────────────────────────────────────
#  Rust
# ─────────────────────────────────────────────────────────────────────────
# include!, include_bytes!, include_str! — block ALL absolute and traversal paths,
# including raw strings (r"...", r#"..."#, br"...", br#"..."#) and macro-defined
# paths via concat!.
_RUST_INCLUDE_DANGEROUS_RE = re.compile(
    r'\binclude(?:_(?:bytes|str))?\s*!\s*\(\s*'
    r'(?:[bB]?[rR]#*)?'                          # optional raw/byte string prefix
    r'"\s*(?:/|[^"]*\.\.)',                       # absolute or traversal
    re.MULTILINE,
)
# Block include via macro indirection: include!(concat!(...)), include!(p!()), etc.
_RUST_INCLUDE_INDIRECT_RE = re.compile(
    r'\binclude(?:_(?:bytes|str))?\s*!\s*\(\s*(?!"|[bB]?[rR]#*")',
    re.MULTILINE,
)
# env!("VAR") and option_env!("VAR") read environment at compile time.
_RUST_ENV_RE = re.compile(r'\b(?:env|option_env)\s*!\s*\(', re.MULTILINE)


# ─────────────────────────────────────────────────────────────────────────
#  Inline assembly — .incbin reads files at compile time (C, C++, Rust)
# ─────────────────────────────────────────────────────────────────────────
_INCBIN_RE = re.compile(r'\.incbin\b', re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────────
#  Pascal — {$I path}, {$INCLUDE path}, {$L file} can read host files.
# ─────────────────────────────────────────────────────────────────────────
_PASCAL_DANGEROUS_DIRECTIVE_RE = re.compile(
    r'\{\$\s*(?:I|INCLUDE|L|LINK|R|RESOURCE)\b[^}]*[/\\]',
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────
#  Haskell — TemplateHaskell allows arbitrary IO at compile time (RCE).
#  CPP pragma re-enables all C-preprocessor attacks. QuasiQuotes likewise.
# ─────────────────────────────────────────────────────────────────────────
_HASKELL_DANGEROUS_PRAGMA_RE = re.compile(
    r'\{-#\s*LANGUAGE[^#]*\b'
    r'(?:TemplateHaskell|QuasiQuotes|CPP|ForeignFunctionInterface|UnsafeIO)\b',
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────
#  C# — #pragma checksum and assembly key/version attributes can probe paths.
# ─────────────────────────────────────────────────────────────────────────
_CSHARP_PRAGMA_CHECKSUM_RE = re.compile(
    r'#\s*pragma\s+checksum\s+"\s*(?:/|[^"]*\.\.)',
    re.MULTILINE,
)
_CSHARP_ASSEMBLY_FILE_RE = re.compile(
    r'\[\s*assembly\s*:\s*[\w.]*(?:KeyFile|FileVersion|AssemblyFile)[^\]]*"\s*(?:/|[^"]*\.\.)',
    re.MULTILINE | re.IGNORECASE,
)


_C_FAMILY_IDS = frozenset({"c", "cpp", "cpp11", "cpp14", "cpp17", "cpp20", "cpp23"})


def validate_source(language_id: str, source_code: str) -> str | None:
    """Return error message if source is rejected, None if OK."""
    # Inline asm .incbin works in any language with an asm! / __asm__ syntax
    if language_id in _C_FAMILY_IDS or language_id == "rust":
        if _INCBIN_RE.search(source_code):
            return "CompileError: .incbin assembler directive is not allowed"

    if language_id == "go":
        if _GO_EMBED_RE.search(source_code):
            return "CompileError: //go:embed directive is not allowed"

    if language_id in _C_FAMILY_IDS:
        if _C_DANGEROUS_INCLUDE_RE.search(source_code):
            return "CompileError: absolute or traversal #include path is not allowed"
        if _C_HAS_INCLUDE_RE.search(source_code):
            return "CompileError: __has_include with absolute or traversal path is not allowed"
        if _C_INCLUDE_INDIRECT_RE.search(source_code):
            return "CompileError: macro-indirected #include is not allowed"

    if language_id == "rust":
        if _RUST_INCLUDE_DANGEROUS_RE.search(source_code):
            return "CompileError: include macro with absolute or traversal path is not allowed"
        if _RUST_INCLUDE_INDIRECT_RE.search(source_code):
            return "CompileError: macro-indirected include is not allowed"
        if _RUST_ENV_RE.search(source_code):
            return "CompileError: env!/option_env! macros are not allowed"

    if language_id == "pascal":
        if _PASCAL_DANGEROUS_DIRECTIVE_RE.search(source_code):
            return "CompileError: {$I} / {$INCLUDE} / {$L} / {$R} with paths is not allowed"

    if language_id == "haskell":
        if _HASKELL_DANGEROUS_PRAGMA_RE.search(source_code):
            return "CompileError: TemplateHaskell, QuasiQuotes, and CPP pragmas are not allowed"

    if language_id == "csharp":
        if _CSHARP_PRAGMA_CHECKSUM_RE.search(source_code):
            return "CompileError: #pragma checksum with absolute or traversal path is not allowed"
        if _CSHARP_ASSEMBLY_FILE_RE.search(source_code):
            return "CompileError: assembly file attributes with paths are not allowed"

    return None
