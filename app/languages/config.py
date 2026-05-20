from dataclasses import dataclass, field


@dataclass
class LanguageConfig:
    """Configuration for a programming language."""
    id: str
    name: str
    version: str
    source_file: str
    compile_cmd: list[str] | None
    run_cmd: list[str]
    # Default limits (can be overridden at the problem or test level)
    time_limit_ms: int = 1000
    memory_limit_mb: int = 256
    compile_timeout_ms: int = 10000
    # Multipliers for interpreted / VM languages
    memory_multiplier: float = 1.0
    time_multiplier: float = 1.0
    # Maksimal process/thread soni (rlimit_nproc). JVM (Java, Kotlin) va
    # boshqa runtime'larga ko'p native thread kerak; default 128 ulargagi
    # OutOfMemoryError'ga olib keladi.
    nproc_limit: int = 128
    # Per-language sandbox tweaks -- each language may require its own
    # mounts or env vars (e.g. /usr/local/cargo for Rust, /opt for Kotlin).
    extra_env: dict[str, str] = field(default_factory=dict)
    # Extra flags injected during the compilation phase (security hardening,
    # performance). Inserted between compile_cmd[0] and the first argument.
    compile_extra_flags: list[str] = field(default_factory=list)


# Languages ordered to match Codeforces #include analogs.
LANGUAGES: dict[str, LanguageConfig] = {
    # -----------------------------------------------------------------
    #  C / C++ family (the most widely used languages in CP)
    # -----------------------------------------------------------------
    "c": LanguageConfig(
        id="c",
        name="C",
        version="GCC 13 (C17)",
        source_file="solution.c",
        compile_cmd=[
            "/usr/bin/gcc", "-std=c17", "-O2", "-pipe", "-Wall", "-static-libgcc",
            "-lm", "-o", "solution", "solution.c",
        ],
        run_cmd=["./solution"],
        time_limit_ms=1000,
        memory_limit_mb=256,
        compile_timeout_ms=10000,
    ),
    "cpp11": LanguageConfig(
        id="cpp11",
        name="C++11",
        version="G++ 13 (C++11)",
        source_file="solution.cpp",
        compile_cmd=["/usr/bin/g++", "-std=c++11", "-O2", "-pipe", "-Wall", "-o", "solution", "solution.cpp"],
        run_cmd=["./solution"],
        compile_timeout_ms=10000,
    ),
    "cpp14": LanguageConfig(
        id="cpp14",
        name="C++14",
        version="G++ 13 (C++14)",
        source_file="solution.cpp",
        compile_cmd=["/usr/bin/g++", "-std=c++14", "-O2", "-pipe", "-Wall", "-o", "solution", "solution.cpp"],
        run_cmd=["./solution"],
        compile_timeout_ms=10000,
    ),
    "cpp": LanguageConfig(
        id="cpp",
        name="C++17",
        version="G++ 13 (C++17)",
        source_file="solution.cpp",
        compile_cmd=["/usr/bin/g++", "-std=c++17", "-O2", "-pipe", "-Wall", "-o", "solution", "solution.cpp"],
        run_cmd=["./solution"],
        compile_timeout_ms=10000,
    ),
    "cpp20": LanguageConfig(
        id="cpp20",
        name="C++20",
        version="G++ 13 (C++20)",
        source_file="solution.cpp",
        compile_cmd=["/usr/bin/g++", "-std=c++20", "-O2", "-pipe", "-Wall", "-o", "solution", "solution.cpp"],
        run_cmd=["./solution"],
        compile_timeout_ms=10000,
    ),
    "cpp23": LanguageConfig(
        id="cpp23",
        name="C++23",
        version="G++ 13 (C++23, draft)",
        source_file="solution.cpp",
        # GCC 13 does not fully support C++23 yet -- offered as "C++23 Draft",
        # matching the Codeforces convention.
        compile_cmd=["/usr/bin/g++", "-std=c++2b", "-O2", "-pipe", "-Wall", "-o", "solution", "solution.cpp"],
        run_cmd=["./solution"],
        compile_timeout_ms=15000,
    ),

    # -----------------------------------------------------------------
    #  Python family
    # -----------------------------------------------------------------
    "py3": LanguageConfig(
        id="py3",
        name="Python 3",
        version="CPython 3.11",
        source_file="solution.py",
        compile_cmd=None,
        run_cmd=["/usr/bin/python3", "solution.py"],
        time_limit_ms=3000,
        memory_limit_mb=512,
        compile_timeout_ms=0,
        time_multiplier=3.0,
        memory_multiplier=2.0,
    ),
    "pypy3": LanguageConfig(
        id="pypy3",
        name="PyPy 3",
        version="PyPy 3.10 (JIT)",
        source_file="solution.py",
        compile_cmd=None,
        run_cmd=["/usr/bin/pypy3", "solution.py"],
        time_limit_ms=3000,
        memory_limit_mb=512,
        compile_timeout_ms=0,
        time_multiplier=2.0,
        memory_multiplier=2.0,
    ),

    # -----------------------------------------------------------------
    #  JVM family
    # -----------------------------------------------------------------
    "java": LanguageConfig(
        id="java",
        name="Java",
        version="OpenJDK 17",
        source_file="Main.java",
        compile_cmd=["/usr/lib/jvm/java-17-openjdk-amd64/bin/javac", "-encoding", "UTF-8", "Main.java"],
        run_cmd=[
            "/usr/lib/jvm/java-17-openjdk-amd64/bin/java",
            "-Xmx{memory}m", "-Xss64m", "-XX:MaxRAM={memory}m",
            "-XX:MaxMetaspaceSize=64m", "-XX:CompressedClassSpaceSize=32m",
            "-XX:+UseSerialGC",
            "-Dfile.encoding=UTF-8",
            "Main",
        ],
        time_limit_ms=2000,
        memory_limit_mb=1024,
        compile_timeout_ms=30000,
        time_multiplier=2.0,
        memory_multiplier=2.0,
        nproc_limit=512,
    ),
    "kotlin": LanguageConfig(
        id="kotlin",
        name="Kotlin",
        version="Kotlin 1.9 (JVM)",
        source_file="solution.kt",
        compile_cmd=[
            "/usr/local/bin/kotlinc", "-include-runtime", "-d", "solution.jar", "solution.kt",
        ],
        run_cmd=[
            "/usr/lib/jvm/java-17-openjdk-amd64/bin/java",
            "-Xmx{memory}m", "-Xss64m", "-XX:+UseSerialGC",
            "-Dfile.encoding=UTF-8",
            "-jar", "solution.jar",
        ],
        time_limit_ms=3000,
        memory_limit_mb=1024,
        compile_timeout_ms=60000,
        time_multiplier=2.0,
        memory_multiplier=2.0,
        nproc_limit=512,
    ),

    # -----------------------------------------------------------------
    #  Static compilers (Rust, Go, FreePascal, Haskell)
    # -----------------------------------------------------------------
    "rust": LanguageConfig(
        id="rust",
        name="Rust",
        version="Rust 1.75 (Edition 2021)",
        source_file="solution.rs",
        compile_cmd=[
            "/usr/local/cargo/bin/rustc", "--edition=2021", "-O", "-C", "opt-level=2",
            "-C", "target-cpu=native", "-o", "solution", "solution.rs",
        ],
        run_cmd=["./solution"],
        time_limit_ms=1000,
        memory_limit_mb=256,
        compile_timeout_ms=30000,
        extra_env={
            "CARGO_HOME": "/tmp/.cargo",
            "RUSTUP_HOME": "/usr/local/rustup",
        },
    ),
    "go": LanguageConfig(
        id="go",
        name="Go",
        version="Go 1.19",
        source_file="solution.go",
        compile_cmd=["/usr/lib/go-1.19/bin/go", "build", "-o", "solution", "solution.go"],
        run_cmd=["./solution"],
        time_limit_ms=2000,
        memory_limit_mb=256,
        compile_timeout_ms=30000,
    ),
    "pascal": LanguageConfig(
        id="pascal",
        name="Pascal",
        version="FreePascal 3.2",
        source_file="solution.pas",
        compile_cmd=["/usr/bin/fpc", "-O2", "-Sg", "-XS", "-vw", "solution.pas"],
        run_cmd=["./solution"],
        time_limit_ms=1000,
        memory_limit_mb=256,
        compile_timeout_ms=15000,
    ),
    "haskell": LanguageConfig(
        id="haskell",
        name="Haskell",
        version="GHC 9.0.2",
        source_file="solution.hs",
        compile_cmd=[
            "/usr/bin/ghc", "-O2",
            "-no-global-package-db",
            "-package-db", "/opt/ghc-pkgdb",
            "-o", "solution", "solution.hs",
        ],
        run_cmd=["./solution"],
        time_limit_ms=2000,
        memory_limit_mb=512,
        compile_timeout_ms=30000,
    ),

    # -----------------------------------------------------------------
    #  Scripting languages
    # -----------------------------------------------------------------
    "js": LanguageConfig(
        id="js",
        name="JavaScript",
        version="Node.js 20",
        source_file="solution.js",
        compile_cmd=None,
        run_cmd=["/usr/bin/node", "--max-old-space-size={memory}", "solution.js"],
        time_limit_ms=3000,
        memory_limit_mb=512,
        compile_timeout_ms=0,
        time_multiplier=2.0,
        memory_multiplier=2.0,
    ),
    "ruby": LanguageConfig(
        id="ruby",
        name="Ruby",
        version="Ruby 3.1",
        source_file="solution.rb",
        compile_cmd=None,
        run_cmd=["/usr/bin/ruby", "solution.rb"],
        time_limit_ms=3000,
        memory_limit_mb=512,
        compile_timeout_ms=0,
        time_multiplier=3.0,
        memory_multiplier=2.0,
    ),

    # -----------------------------------------------------------------
    #  .NET
    # -----------------------------------------------------------------
    "csharp": LanguageConfig(
        id="csharp",
        name="C#",
        version=".NET 8 (Mono runtime)",
        source_file="solution.cs",
        # mono-csc -- follows the same pattern used by Codeforces
        compile_cmd=["/usr/bin/mcs", "-optimize+", "-out:solution.exe", "solution.cs"],
        run_cmd=["/usr/bin/mono", "solution.exe"],
        time_limit_ms=2000,
        memory_limit_mb=512,
        compile_timeout_ms=20000,
        time_multiplier=2.0,
        memory_multiplier=2.0,
    ),
}

# Aliases -- point to the canonical config so get_all_languages() returns unique entries.
LANGUAGES["cpp17"] = LANGUAGES["cpp"]
LANGUAGES["py"] = LANGUAGES["py3"]


def get_language(language_id: str) -> LanguageConfig | None:
    """Get language configuration by ID."""
    return LANGUAGES.get(language_id)


def get_all_languages() -> list[LanguageConfig]:
    """Get all supported languages (unique, no alias duplicates)."""
    seen: set[int] = set()
    result: list[LanguageConfig] = []
    for cfg in LANGUAGES.values():
        if id(cfg) not in seen:
            seen.add(id(cfg))
            result.append(cfg)
    return result
