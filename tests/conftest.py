import os
from unittest.mock import patch

os.environ.setdefault("INTERNAL_TOKEN", "test-token-for-ci")

# Nsjail binary doesn't exist on dev machines. Patch the check so the module
# can be imported without RuntimeError during collection.
_orig_exists = os.path.exists


def _patched_exists(path):
    if path == "/usr/bin/nsjail":
        return True
    return _orig_exists(path)


patch("os.path.exists", side_effect=_patched_exists).start()
