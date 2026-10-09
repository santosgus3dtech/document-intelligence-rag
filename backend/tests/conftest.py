"""Keep unit tests independent from a developer's or container's app settings."""
from __future__ import annotations

import os
from tempfile import TemporaryDirectory

import pytest


APP_SETTINGS = ("DOC_INTEL_DATABASE_URL", "DOC_INTEL_DEMO", "DOC_INTEL_API_TOKENS", "DOC_INTEL_EXTRACTOR")

# app.main constructs its module-level app during test collection, before
# fixtures run. Never let that import connect to an inherited application DB.
for setting in APP_SETTINGS:
    os.environ.pop(setting, None)
IMPORT_STORAGE = TemporaryDirectory(prefix="document-intel-test-import-")
os.environ["DOC_INTEL_STORAGE"] = IMPORT_STORAGE.name


@pytest.fixture(autouse=True)
def isolated_application_settings(monkeypatch, tmp_path):
    for setting in APP_SETTINGS:
        monkeypatch.delenv(setting, raising=False)
    monkeypatch.setenv("DOC_INTEL_STORAGE", str(tmp_path / "default-storage"))
    # DOC_INTEL_TEST_DATABASE_URL is intentionally retained. Only the native
    # integration test passes it explicitly to build_app(database_url=...).
