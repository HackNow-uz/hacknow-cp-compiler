FROM debian:bookworm-slim

LABEL org.opencontainers.image.source="https://github.com/HackNow-uz/hacknow-cp-compiler"
LABEL org.opencontainers.image.description="Production-grade competitive programming judge with nsjail sandboxing"
LABEL org.opencontainers.image.licenses="MIT"

# ─────────────────────────────────────────────────────────────────────────
#  Base packages + nsjail build deps + competitive programming languages
# ─────────────────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build essentials
    build-essential pkg-config ca-certificates curl wget git jq time uidmap \
    bison flex libprotobuf-dev libnl-route-3-dev protobuf-compiler \
    # C/C++
    gcc g++ \
    # Python (CPython + PyPy)
    python3 python3-pip pypy3 \
    # Node.js
    nodejs \
    # JVM (Java)
    openjdk-17-jdk-headless \
    # Go
    golang \
    # FreePascal (IOI traditional)
    fpc \
    # Haskell (GHC compiler)
    ghc \
    # Ruby
    ruby ruby-full \
    # C# / .NET (Mono runtime — Codeforces style)
    mono-mcs mono-runtime \
    && rm -rf /var/lib/apt/lists/* \
    # GHC package database: initialize and copy to /opt for nsjail visibility
    && ghc-pkg recache \
    && cp -r /usr/lib/ghc/package.conf.d /opt/ghc-pkgdb

# ─────────────────────────────────────────────────────────────────────────
#  Rust — pinned 1.75 stable
# ─────────────────────────────────────────────────────────────────────────
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
    sh -s -- -y --default-toolchain 1.75.0 --profile minimal --no-modify-path && \
    chmod -R a+rX /usr/local/rustup /usr/local/cargo

# ─────────────────────────────────────────────────────────────────────────
#  Kotlin — pinned 1.9.22
# ─────────────────────────────────────────────────────────────────────────
ENV KOTLIN_VERSION=1.9.22
RUN cd /tmp && \
    curl -sSL "https://github.com/JetBrains/kotlin/releases/download/v${KOTLIN_VERSION}/kotlin-compiler-${KOTLIN_VERSION}.zip" -o kotlin.zip && \
    apt-get update && apt-get install -y --no-install-recommends unzip && \
    unzip -q kotlin.zip -d /opt && \
    ln -s /opt/kotlinc/bin/kotlinc /usr/local/bin/kotlinc && \
    ln -s /opt/kotlinc/bin/kotlin /usr/local/bin/kotlin && \
    rm -f kotlin.zip && \
    apt-get remove -y unzip && \
    rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────────────────────────────────
#  Nsjail 3.4 — built from source for reproducibility
# ─────────────────────────────────────────────────────────────────────────
RUN git clone https://github.com/google/nsjail.git /tmp/nsjail && \
    cd /tmp/nsjail && git checkout 3.4 && \
    make && \
    cp nsjail /usr/bin/nsjail && \
    rm -rf /tmp/nsjail

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip3 install --default-timeout=100 --no-cache-dir --break-system-packages -r requirements.txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Sandbox user (uid 1000 — matches nsjail user mapping)
RUN useradd -m -u 1000 sandbox

# Sandbox directories
RUN mkdir -p /sandbox /compiler-temp /etc/nsjail && \
    chmod 1777 /sandbox /compiler-temp

# Nsjail bindmount configuration
COPY docker/nsjail_bindmounts.conf /etc/nsjail/bindmounts.conf

# Application code
COPY app/ ./app/

EXPOSE 8000

USER sandbox

# Uvicorn workers: tune via UVICORN_WORKERS env variable.
# Each worker runs its own async event loop with nsjail semaphores.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-4}"]
