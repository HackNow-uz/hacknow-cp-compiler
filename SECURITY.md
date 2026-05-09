# CP Compiler — Security Design Document

**Service**: hacknow-cp-compiler v2.2  
**Last updated**: 2026-05-09

## Scope

This service compiles and executes arbitrary user code for competitive programming judging. It accepts source code via authenticated API, runs it inside an nsjail sandbox, and returns stdout/stderr/resource usage.

**In scope**: preventing sandboxed code from reading host files, exfiltrating data over the network, exhausting host resources, or escaping to the container/host.

**Out of scope**: application-layer DoS against the API itself (rate limiting is the caller's responsibility), supply-chain attacks on compiler toolchains, and vulnerabilities in the host kernel.

## Threat Model

### T1 — Sandbox Escape via Syscall

**Threat**: Sandboxed process uses a privileged syscall (e.g., `bpf`, `userfaultfd`, `io_uring`) to escape nsjail namespaces.  
**Mitigation**: nsjail runs with `--mode o` (one-shot), user/mount/PID/net namespaces, `--disable_proc`, `--iface_no_lo`. Docker seccomp profile blocks `bpf`, `userfaultfd`, `io_uring_*`, `kexec_load`, `keyctl`. Container runs `no-new-privileges:true` and drops `NET_ADMIN`, `MKNOD`, `AUDIT_WRITE`.  
**Residual risk**: Kernel zero-day in an allowed syscall. Mitigate by keeping the host kernel patched.

### T2 — File System Read (Secrets, Host Data)

**Threat**: Code reads `/etc/shadow`, env files, or INTERNAL_TOKEN via `#include`, `include_bytes!`, `env!()`, or `//go:embed`.  
**Mitigation**: (1) Bindmounts are selective — only linker cache, SSL certs, locale, language toolchains are mounted read-only. Full `/etc` is NOT mounted. (2) Source-level validation blocks absolute-path includes, path traversal (`..`), Go embed directives, and Rust `env!`/`option_env!` macros before compilation starts. (3) nsjail maps user to UID 1000 with no capabilities.  
**Residual risk**: A new language's compiler may read files via mechanisms not yet covered by source validation.

### T3 — Network Exfiltration

**Threat**: Sandboxed code opens a socket to send stolen data or download payloads.  
**Mitigation**: nsjail `--iface_no_lo` disables all network interfaces inside the sandbox — no loopback, no external connectivity. The container itself binds only to `127.0.0.1:8000`.  
**Residual risk**: None under normal operation. If nsjail's network namespace is bypassed, Docker's `NET_ADMIN` cap_drop limits further abuse.

### T4 — Resource Exhaustion (Fork Bomb, Memory, Disk)

**Threat**: Code forks aggressively, allocates unbounded memory, or writes large files to exhaust host resources.  
**Mitigation**: nsjail enforces `--rlimit_nproc 512`, `--rlimit_as` (4x requested, capped), `--rlimit_fsize` (16 MB), `--max_cpus 1`, wall-clock + CPU time limits. `/tmp` inside sandbox is a 32 MB tmpfs. The compiler temp dir is a 512 MB tmpfs at the container level. Docker resource limits cap the container at 2 GB RAM and 2 CPUs. Concurrency semaphores (global + per-language) prevent oversubscription.  
**Residual risk**: A slow leak within limits could degrade performance over hours. Health check + restart policy handles this.

### T5 — Token Theft / Auth Bypass

**Threat**: Attacker calls the API without a valid token, or extracts INTERNAL_TOKEN from inside the sandbox.  
**Mitigation**: Bearer token auth with constant-time comparison (`secrets.compare_digest`). Tokens shorter than 32 chars or with low entropy are rejected at startup. The token is passed via `.env` (not baked into the image). Inside the sandbox, env vars are explicitly set — `INTERNAL_TOKEN` is never forwarded. Source-level Rust `env!()` blocking prevents compile-time env exfiltration.  
**Residual risk**: If `.env` file permissions are too open on the host, local users could read it.

### T6 — Compiler-Based Attacks

**Threat**: Malicious code exploits compiler bugs (e.g., GCC LTO bugs, `#pragma` abuse) to write outside the sandbox during compilation.  
**Mitigation**: Compilation also runs inside nsjail with the same namespace isolation. C/C++ gets `-ffile-prefix-map=/sandbox=.` and depth limits. Compile timeout prevents resource exhaustion during compilation.  
**Residual risk**: Compiler zero-days. Keep toolchains updated.

## Architecture Layers

```
User code
  │
  ├─ Source validation (regex: blocks #include "/../", env!(), //go:embed)
  │
  ├─ nsjail (Layer 1)
  │   ├─ User/PID/mount/net namespaces
  │   ├─ UID 1000, no capabilities
  │   ├─ No network interfaces
  │   ├─ Read-only selective bindmounts
  │   ├─ rlimits: CPU, memory, fsize, nproc
  │   └─ /proc disabled (--disable_proc)
  │
  ├─ Docker container (Layer 2)
  │   ├─ seccomp profile (blocks bpf, io_uring, kexec, keyctl, userfaultfd)
  │   ├─ CAPs: only SYS_ADMIN, SYS_PTRACE, SYS_CHROOT, SETUID, SETGID
  │   ├─ no-new-privileges
  │   ├─ 2 GB memory / 2 CPU limit
  │   └─ tmpfs for compiler workspace
  │
  └─ Host kernel (Layer 3)
      └─ Standard kernel isolation; keep patched
```

## Known Limitations

1. **Host PID visibility**: `/proc` is bind-mounted read-only for JVM/Mono/rustc/GHC compatibility. Sandboxed code can enumerate host PIDs via `/proc`. This leaks process names but not memory. `--disable_proc` prevents new procfs mounts but the bind-mount is still visible.

2. **Timing side channels**: Execution time is measured and returned to the caller. Code can measure its own wall-clock time. No mitigation — inherent to a judge system.

3. **Compiler information leakage**: Error messages from compilers may reveal absolute paths, installed package versions, or kernel version strings. `-ffile-prefix-map` reduces this for C/C++ but not all languages.

4. **No seccomp inside nsjail**: nsjail's own seccomp filtering is not enabled (we rely on Docker-level seccomp). A defense-in-depth improvement would be adding nsjail-level seccomp via `--seccomp_string`.

5. **AppArmor disabled**: `apparmor:unconfined` is set because nsjail's mount namespace operations conflict with default AppArmor profiles. A custom AppArmor profile would improve defense-in-depth.

6. **Shared kernel**: All sandboxes share the host kernel. A kernel exploit in any sandbox compromises everything. gVisor or Firecracker would provide stronger isolation but add latency.

## Reporting Vulnerabilities

If you find a sandbox escape or authentication bypass:

1. **Do not** open a public issue.
2. Email **hacknow.uz@gmail.com** with reproduction steps.
3. We aim to acknowledge within 48 hours and patch within 7 days for critical issues.

## Production Hardening Checklist

- [ ] `INTERNAL_TOKEN` is a cryptographically random string >= 32 characters
- [ ] `.env` file is chmod 600, owned by root or the deploy user
- [ ] Docker socket is not mounted into the container
- [ ] Host kernel is >= 5.15 with user namespace support
- [ ] `docker-compose.yml` uses the seccomp profile (`seccomp:./docker/seccomp-profile.json`)
- [ ] Container image is rebuilt periodically to pick up compiler security patches
- [ ] API is behind a reverse proxy with rate limiting (not handled by this service)
- [ ] `/compiler-temp` tmpfs is sized appropriately for expected concurrency
- [ ] Log level is `WARNING` or above in production (no debug logging of user code)
- [ ] Health check endpoint (`/api/v1/health`) is monitored
- [ ] Container restart policy is `unless-stopped` (handles OOM kills)
- [ ] Network: container port bound to `127.0.0.1`, not `0.0.0.0`
