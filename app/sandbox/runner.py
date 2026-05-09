"""Nsjail sandbox runner with compilation cache and CPU-aware concurrency."""
import asyncio
import os
import shutil
import tempfile
import logging
import time
from dataclasses import dataclass

from app.config import settings
from app.languages.config import LanguageConfig
from .validation import validate_source
from .cache import _CompileCache

logger = logging.getLogger(__name__)

_GO_LANG_IDS = frozenset({"go"})
_JVM_LANG_IDS = frozenset({"java", "kotlin"})
_HASKELL_LANG_IDS = frozenset({"haskell"})


@dataclass
class ExecutionResult:
    """Result of code execution in Nsjail."""
    exit_code: int
    stdout: str
    stderr: str
    time_ms: int
    memory_kb: int
    timed_out: bool = False
    memory_exceeded: bool = False
    output_limit_exceeded: bool = False


class NsjailRunner:
    """Nsjail sandbox with CPU-aware concurrency and compilation cache."""

    def __init__(self):
        self.nsjail_path = "/usr/bin/nsjail"
        self._ensure_nsjail()

        cpu_count = os.cpu_count() or 2
        self.cpu_count = cpu_count
        self.slots_per_language = (
            settings.per_language_concurrency_slots
            if settings.per_language_concurrency_slots > 0
            else max(cpu_count * 4, 6)
        )
        self._global_slots = (
            settings.global_concurrency_slots
            if settings.global_concurrency_slots > 0
            else max(cpu_count * 6, 12)
        )
        self._global_semaphore = asyncio.Semaphore(self._global_slots)
        self.semaphores = {}
        self._cached_bindmounts: list[str] | None = None
        self._compile_cache = _CompileCache(
            max_entries=settings.compile_cache_max_entries,
            ttl_seconds=settings.compile_cache_ttl_seconds,
        )
        logger.info(
            "NsjailRunner: %d CPUs, %d slots/language, %d global slots",
            cpu_count, self.slots_per_language, self._global_slots,
        )

    def get_semaphore(self, language_id: str) -> asyncio.Semaphore:
        if language_id not in self.semaphores:
            self.semaphores[language_id] = asyncio.Semaphore(self.slots_per_language)
        return self.semaphores[language_id]

    def _ensure_nsjail(self):
        if not os.path.exists(self.nsjail_path):
            raise RuntimeError(
                "Nsjail binary not found at /usr/bin/nsjail. "
                "Install nsjail or check the container image."
            )

    _DEFAULT_BINDMOUNTS_RO: list[str] = [
        "/usr/lib:/usr/lib",
        "/usr/lib64:/usr/lib64",
        "/usr/libexec:/usr/libexec",
        "/usr/include:/usr/include",
        "/usr/share:/usr/share",
        "/usr/bin:/usr/bin",
        "/bin:/bin",
        "/lib:/lib",
        "/lib64:/lib64",
        "/etc:/etc",
        "/proc:/proc",
        "/dev/urandom:/dev/urandom",
        "/dev/null:/dev/null",
    ]

    _BINDMOUNTS_CONFIG_FILE: str = os.environ.get(
        "NSJAIL_BINDMOUNTS_CONFIG",
        "/etc/nsjail/bindmounts.conf",
    )

    def _load_bindmounts(self) -> list[str]:
        """Load bindmount list from config file, cached after first call."""
        if self._cached_bindmounts is not None:
            return self._cached_bindmounts

        config_path = self._BINDMOUNTS_CONFIG_FILE
        if os.path.isfile(config_path):
            try:
                mounts = []
                with open(config_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if ":" not in line:
                            logger.warning(
                                "Nsjail bindmount config: invalid line '%s' -- skipped", line,
                            )
                            continue
                        mounts.append(line)
                if mounts:
                    logger.info(
                        "Nsjail bindmounts loaded from config: %d mounts (%s)",
                        len(mounts), config_path,
                    )
                    self._cached_bindmounts = mounts
                    return self._cached_bindmounts
                logger.warning(
                    "Nsjail bindmounts config is empty -- using defaults (%s)", config_path,
                )
            except Exception as e:
                logger.error("Nsjail bindmounts config read error -- using defaults: %s", e)
        else:
            logger.debug(
                "Nsjail bindmounts config not found -- using defaults (%s)", config_path,
            )
        self._cached_bindmounts = list(self._DEFAULT_BINDMOUNTS_RO)
        return self._cached_bindmounts

    def _build_env_args(self, language: LanguageConfig | None) -> list[str]:
        """Build --env args for nsjail. Language-specific vars only added when needed."""
        base = {
            "PATH": "/usr/local/cargo/bin:/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "HOME": "/tmp",
        }

        lang_id = language.id if language else None

        if lang_id in _GO_LANG_IDS:
            base["GOROOT"] = "/usr/lib/go-1.19"
            base["GOCACHE"] = "/tmp/.cache"
            base["GOTMPDIR"] = "/tmp"

        if lang_id in _JVM_LANG_IDS:
            base["LD_LIBRARY_PATH"] = ":".join([
                "/usr/lib/jvm/java-17-openjdk-amd64/lib/server",
                "/usr/lib/jvm/java-17-openjdk-amd64/lib/jli",
                "/usr/lib/jvm/java-17-openjdk-amd64/lib",
                "/usr/lib/x86_64-linux-gnu",
            ])

        if lang_id in _HASKELL_LANG_IDS:
            base["GHC_PACKAGE_PATH"] = "/opt/ghc-pkgdb"

        if language and language.extra_env:
            base.update(language.extra_env)

        env_args: list[str] = []
        for k, v in base.items():
            env_args += ["--env", f"{k}={v}"]
        return env_args

    def _get_nsjail_command(
        self,
        work_dir: str,
        time_limit_ms: int,
        memory_limit_mb: int,
        cmd: list[str],
        language: LanguageConfig | None = None,
    ) -> list[str]:
        """Build the nsjail command line."""
        cpu_limit_sec = (time_limit_ms + 999) // 1000
        wall_limit_sec = cpu_limit_sec + 3

        is_managed = any(
            tok in part for part in cmd for tok in (
                "java", "mono", "kotlin",
            )
        )
        if is_managed:
            rlimit_as_mb = max(memory_limit_mb * 4, 2048)
        elif language and language.id in ("haskell", "rust"):
            rlimit_as_mb = max(memory_limit_mb * 4, 1024)
        else:
            rlimit_as_mb = max(memory_limit_mb * 4, 512)

        bindmounts_ro = self._load_bindmounts()

        mount_args: list[str] = []
        for mount in bindmounts_ro:
            host_path = mount.split(":")[0]
            if os.path.exists(host_path):
                mount_args += ["--bindmount_ro", mount]
            else:
                logger.debug("Nsjail bindmount skip (not found): %s", mount)

        args = [
            self.nsjail_path,
            "--mode", "o",
            "--quiet",
            "--max_cpus", "1",
            "--time_limit", str(wall_limit_sec),
            "--rlimit_cpu", str(cpu_limit_sec),
            "--rlimit_as", str(rlimit_as_mb),
            "--rlimit_fsize", str(settings.output_limit_mb),
            "--rlimit_nproc", "512",
            "--rlimit_stack", "soft",
            "--user", "1000",
            "--group", "1000",
            "--cwd", "/sandbox",
            "--disable_proc",
            "--iface_no_lo",
        ]

        args += mount_args
        args += self._build_env_args(language)

        args += [
            "-m", "none:/tmp:tmpfs:size=33554432",
            "--bindmount", f"{work_dir}:/sandbox",
            "--rw",
            "--",
        ]

        return args + cmd

    def _validate_source(self, language_id: str, source_code: str) -> str | None:
        return validate_source(language_id, source_code)

    async def _compile_in_nsjail(
        self,
        language: LanguageConfig,
        work_dir: str,
    ) -> tuple[int, str]:
        """Run compilation inside nsjail. Returns (returncode, combined_output)."""
        compile_timeout_sec = (language.compile_timeout_ms or 30000) / 1000.0

        extra_flags: list[str] = []
        lang_id = language.id
        if lang_id in ("c", "cpp", "cpp11", "cpp14", "cpp17", "cpp20", "cpp23"):
            extra_flags = [
                "-ffile-prefix-map=/sandbox=.",
                "-ftemplate-depth=1024",
                "-fconstexpr-depth=1024",
            ]

        if language.compile_extra_flags:
            extra_flags = list(language.compile_extra_flags) + extra_flags

        compile_cmd = list(language.compile_cmd)
        if extra_flags:
            insert_pos = 1
            compile_cmd = compile_cmd[:insert_pos] + extra_flags + compile_cmd[insert_pos:]

        nsjail_cmd = self._get_nsjail_command(
            work_dir=work_dir,
            time_limit_ms=language.compile_timeout_ms or 30000,
            memory_limit_mb=1024,
            cmd=compile_cmd,
            language=language,
        )

        proc = await asyncio.create_subprocess_exec(
            *nsjail_cmd,
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(),
                timeout=compile_timeout_sec + 10.0,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            return 1, "Compile timeout"

        combined = (stdout_b + stderr_b).decode("utf-8", "replace")
        return proc.returncode, combined

    async def _read_capped(self, stream: asyncio.StreamReader, max_bytes: int) -> bytes:
        """Read at most max_bytes from stream; stop early if limit reached."""
        chunks = []
        total = 0
        while True:
            try:
                chunk = await stream.read(65536)
            except Exception:
                break
            if not chunk:
                break
            remaining = max_bytes - total
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                total += remaining
                break
            chunks.append(chunk)
            total += len(chunk)
        return b"".join(chunks)

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API: Single execution (for /api/v1/run endpoint)
    # ─────────────────────────────────────────────────────────────────────────

    async def execute(
        self,
        language: LanguageConfig,
        source_code: str,
        input_data: str,
        time_limit_ms: int,
        memory_limit_mb: int,
    ) -> tuple[ExecutionResult, str, int]:
        """Compile and execute code in an nsjail sandbox."""
        work_dir = tempfile.mkdtemp(dir=settings.compiler_temp_dir)
        os.chmod(work_dir, 0o700)

        compile_output = ""
        compile_time_ms = 0

        try:
            validation_error = self._validate_source(language.id, source_code)
            if validation_error:
                return ExecutionResult(1, "", "", 0, 0), validation_error, 0

            source_path = os.path.join(work_dir, language.source_file)
            with open(source_path, "w") as f:
                f.write(source_code)

            if language.compile_cmd:
                start_c = time.time()
                returncode, compile_output = await self._compile_in_nsjail(language, work_dir)
                compile_time_ms = int((time.time() - start_c) * 1000)

                if returncode != 0:
                    return ExecutionResult(1, "", "", 0, 0), compile_output, compile_time_ms

            result = await self._run_in_nsjail(
                language=language,
                work_dir=work_dir,
                input_data=input_data,
                time_limit_ms=time_limit_ms,
                memory_limit_mb=memory_limit_mb,
            )
            return result, "", compile_time_ms

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API: Judge (compile once, run N times)
    # ─────────────────────────────────────────────────────────────────────────

    async def compile_once(
        self,
        language: LanguageConfig,
        source_code: str,
    ) -> tuple[str | None, str, int]:
        """
        Compile code ONCE and return the work directory with compiled artifacts.
        For interpreted languages, just writes the source file.

        Returns: (work_dir or None on CE, compile_output, compile_time_ms)

        Caller MUST call release_compiled() when done, OR clean up work_dir
        with shutil.rmtree().
        """
        validation_error = self._validate_source(language.id, source_code)
        if validation_error:
            return None, validation_error, 0

        # ── Cache check ────────────────────────────────────────────────
        if language.compile_cmd:
            cached = self._compile_cache.get(language.id, source_code)
            if cached and os.path.isdir(cached.cache_dir):
                work_dir = tempfile.mkdtemp(dir=settings.compiler_temp_dir)
                os.chmod(work_dir, 0o700)
                try:
                    for item in os.listdir(cached.cache_dir):
                        src = os.path.join(cached.cache_dir, item)
                        dst = os.path.join(work_dir, item)
                        if os.path.isfile(src):
                            try:
                                os.link(src, dst)
                            except OSError:
                                shutil.copy2(src, dst)
                        elif os.path.isdir(src):
                            shutil.copytree(src, dst)
                    for item in os.listdir(work_dir):
                        try:
                            os.chmod(os.path.join(work_dir, item), 0o755)
                        except OSError:
                            pass
                    logger.debug(
                        "compile_cache HIT: lang=%s, cache_dir=%s",
                        language.id, cached.cache_dir,
                    )
                    return work_dir, cached.compile_output, cached.compile_time_ms
                except Exception as e:
                    logger.warning("compile_cache hardlink failed, recompiling: %s", e)
                    shutil.rmtree(work_dir, ignore_errors=True)

        # ── Compile ────────────────────────────────────────────────────
        work_dir = tempfile.mkdtemp(dir=settings.compiler_temp_dir)
        os.chmod(work_dir, 0o700)

        source_path = os.path.join(work_dir, language.source_file)
        with open(source_path, "w") as f:
            f.write(source_code)

        if language.compile_cmd:
            start_c = time.time()
            returncode, compile_output = await self._compile_in_nsjail(language, work_dir)
            compile_time_ms = int((time.time() - start_c) * 1000)

            if returncode != 0:
                shutil.rmtree(work_dir, ignore_errors=True)
                return None, compile_output, compile_time_ms

            # ── Cache store ────────────────────────────────────────────
            if settings.compile_cache_max_entries > 0:
                try:
                    cache_dir = tempfile.mkdtemp(
                        dir=settings.compiler_temp_dir, prefix="ccache_",
                    )
                    os.chmod(cache_dir, 0o700)
                    for item in os.listdir(work_dir):
                        src = os.path.join(work_dir, item)
                        dst = os.path.join(cache_dir, item)
                        if os.path.isfile(src):
                            try:
                                os.link(src, dst)
                            except OSError:
                                shutil.copy2(src, dst)
                        elif os.path.isdir(src):
                            shutil.copytree(src, dst)
                    self._compile_cache.put(
                        language.id, source_code, cache_dir,
                        compile_output, compile_time_ms,
                    )
                    logger.debug(
                        "compile_cache STORE: lang=%s, compile_ms=%d",
                        language.id, compile_time_ms,
                    )
                except Exception as e:
                    logger.warning("compile_cache store failed: %s", e)

            return work_dir, "", compile_time_ms

        return work_dir, "", 0

    def release_compiled(self, language_id: str, source_code: str) -> None:
        """Release cache ref_count when judge is done with compiled artifacts."""
        self._compile_cache.release(language_id, source_code)

    async def run_test(
        self,
        language: LanguageConfig,
        compiled_dir: str,
        input_data: str,
        time_limit_ms: int,
        memory_limit_mb: int,
    ) -> ExecutionResult:
        """Run a single test case using pre-compiled artifacts."""
        work_dir = tempfile.mkdtemp(dir=settings.compiler_temp_dir)
        os.chmod(work_dir, 0o700)

        try:
            for item in os.listdir(compiled_dir):
                src = os.path.join(compiled_dir, item)
                dst = os.path.join(work_dir, item)
                if os.path.isfile(src):
                    try:
                        os.link(src, dst)
                    except OSError:
                        shutil.copy2(src, dst)
                elif os.path.isdir(src):
                    shutil.copytree(src, dst)

            for item in os.listdir(work_dir):
                try:
                    os.chmod(os.path.join(work_dir, item), 0o555)
                except OSError:
                    pass

            return await self._run_in_nsjail(
                language=language,
                work_dir=work_dir,
                input_data=input_data,
                time_limit_ms=time_limit_ms,
                memory_limit_mb=memory_limit_mb,
            )

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL: Shared nsjail execution logic
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_in_nsjail(
        self,
        language: LanguageConfig,
        work_dir: str,
        input_data: str,
        time_limit_ms: int,
        memory_limit_mb: int,
    ) -> ExecutionResult:
        """Run code in nsjail sandbox with resource tracking."""
        run_cmd = []
        for part in language.run_cmd:
            if "{memory}" in part:
                run_cmd.append(part.replace("{memory}", str(memory_limit_mb)))
            else:
                run_cmd.append(part)

        time_wrapper = [
            "/usr/bin/time",
            "-f", "RESOURCE_USAGE\nUSER_TIME:%U\nSYS_TIME:%S\nMEM:%M\nEXIT:%x",
        ]

        nsjail_cmd = self._get_nsjail_command(
            work_dir=work_dir,
            time_limit_ms=time_limit_ms,
            memory_limit_mb=memory_limit_mb,
            cmd=time_wrapper + run_cmd,
            language=language,
        )

        semaphore = self.get_semaphore(language.id)
        max_output_bytes = settings.output_limit_mb * 1024 * 1024

        async with self._global_semaphore, semaphore:
            try:
                logger.debug("Nsjail CMD: %s", " ".join(nsjail_cmd))
                start_t = time.time()
                proc = await asyncio.create_subprocess_exec(
                    *nsjail_cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                input_bytes = input_data.encode()

                async def _feed_stdin():
                    try:
                        proc.stdin.write(input_bytes)
                        await proc.stdin.drain()
                    except Exception:
                        pass
                    finally:
                        try:
                            proc.stdin.close()
                        except Exception:
                            pass

                try:
                    wall_timeout = (time_limit_ms / 1000.0) + 5.0
                    _, stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        asyncio.gather(
                            _feed_stdin(),
                            self._read_capped(proc.stdout, max_output_bytes),
                            self._read_capped(proc.stderr, max_output_bytes),
                        ),
                        timeout=wall_timeout,
                    )
                    await proc.wait()
                    elapsed_ms = int((time.time() - start_t) * 1000)
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    logger.warning("Nsjail TIMEOUT")
                    return ExecutionResult(124, "", "", time_limit_ms + 1, 0, True)

                stdout_raw = stdout_bytes.decode("utf-8", "replace")
                stderr_raw = stderr_bytes.decode("utf-8", "replace")

                if len(stdout_bytes) >= max_output_bytes:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return ExecutionResult(
                        exit_code=1,
                        stdout=stdout_raw,
                        stderr="Output limit exceeded",
                        time_ms=elapsed_ms,
                        memory_kb=0,
                        output_limit_exceeded=True,
                    )

                exit_code = proc.returncode
                stderr_str, time_from_wrapper, mem_kb = self._parse_time_output(stderr_raw)

                final_time_ms = int(time_from_wrapper * 1000) if time_from_wrapper > 0 else elapsed_ms

                if exit_code != 0:
                    logger.debug(
                        "Nsjail non-zero exit: exit_code=%d, stderr=%.500s",
                        exit_code, stderr_str,
                    )
                    if not stderr_str and not stdout_raw:
                        stderr_str = "Sandbox execution failed (Possible namespace or mount error). Check Docker privileges."

                return ExecutionResult(
                    exit_code=exit_code,
                    stdout=stdout_raw,
                    stderr=stderr_str,
                    time_ms=final_time_ms,
                    memory_kb=mem_kb,
                    timed_out=(exit_code in (137, 124, 152)),
                    memory_exceeded=(exit_code == 139)
                )
            except Exception as e:
                logger.error("Nsjail sub-process error: %s", e)
                return ExecutionResult(1, "", str(e), 0, 0)

    def _parse_time_output(self, stderr: str) -> tuple[str, float, int]:
        """Parse GNU time output from stderr. Returns (user_stderr, cpu_time_sec, memory_kb)."""
        if not stderr:
            return "", 0.0, 0

        lines = stderr.splitlines()
        filtered = []
        user_time_sec = 0.0
        sys_time_sec = 0.0
        mem_kb = 0
        is_parsing_usage = False

        for line in lines:
            if line.strip() == "RESOURCE_USAGE":
                is_parsing_usage = True
                continue

            if is_parsing_usage:
                if line.startswith("USER_TIME:"):
                    try:
                        user_time_sec = float(line.split(":", 1)[1])
                    except Exception:
                        pass
                elif line.startswith("SYS_TIME:"):
                    try:
                        sys_time_sec = float(line.split(":", 1)[1])
                    except Exception:
                        pass
                elif line.startswith("MEM:"):
                    try:
                        mem_kb = int(line.split(":", 1)[1])
                    except Exception:
                        pass
                elif line.startswith("EXIT:"):
                    pass
                continue

            if line.startswith('[W][') or line.startswith('[I][') or \
               line.startswith('[E][') or line.startswith('[F]['):
                continue

            filtered.append(line)

        cpu_time_sec = user_time_sec + sys_time_sec
        return "\n".join(filtered).strip(), cpu_time_sec, mem_kb


# Global singleton
nsjail_runner = NsjailRunner()
