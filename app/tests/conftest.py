"""Test environment setup.

This MUST run before anything imports ``app.backend.config``, because ``settings``
is instantiated at import time and is not re-read afterwards. pytest imports
conftest.py before collecting any test module, which makes this the only reliable
place to put it -- setting these at the top of an individual test file works only
if that file happens to be imported first, which is a bug waiting for someone to
add a test module earlier in the alphabet.
"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="grounded-tests-")

# Deterministic stub provider: no network, no API key. Every layer beneath the
# provider is the real one.
os.environ["GROUNDED_LLM_PROVIDER"] = "echo"
os.environ["GROUNDED_DB_PATH"] = os.path.join(_TMP, "test.sqlite3")
# Ignore any developer .env so a local config cannot change test outcomes.
os.environ["GROUNDED_ANTHROPIC_API_KEY"] = ""
