# Contributing to CP Compiler

Thank you for your interest in contributing! This guide will help you get started.

## Development Setup

### Prerequisites

- Docker with BuildKit
- Python 3.11+
- Linux (nsjail requires Linux namespaces)

### Local Development

```bash
# Clone the repo
git clone https://github.com/HackNow-uz/hacknow-cp-compiler.git
cd hacknow-cp-compiler

# Copy environment config
cp .env.example .env
# Edit .env and set INTERNAL_TOKEN to a secure random string

# Build and run
docker compose up --build

# The service is now available at http://localhost:8000
# API docs: http://localhost:8000/docs
```

### Running Without Docker

If you have nsjail installed on your Linux system:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Set environment variables
export INTERNAL_TOKEN="your-secure-token-here"
export LOG_FORMAT=text
export COMPILER_TEMP_DIR=/tmp/cp-compiler

mkdir -p $COMPILER_TEMP_DIR

uvicorn app.main:app --reload --port 8000
```

## Adding a New Language

1. Install the toolchain in the `Dockerfile`
2. Add a `LanguageConfig` entry in `app/languages/config.py`
3. Add any required bindmounts to `docker/nsjail_bindmounts.conf`
4. Test with a "Hello, World!" submission

## Code Style

- Python 3.11+ with type hints
- Follow existing patterns in the codebase
- English comments and docstrings
- No unnecessary abstractions

## Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Make your changes
4. Ensure all existing tests still pass
5. Submit a PR with a clear description

## Reporting Issues

- Use GitHub Issues
- Include: steps to reproduce, expected vs actual behavior, environment details
- For security issues, please email hacknow.uz@gmail.com instead of opening a public issue

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
