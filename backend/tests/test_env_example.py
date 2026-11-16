import re
from pathlib import Path

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


def _declared_keys(path: Path) -> set[str]:
    return {m.group(1) for line in path.read_text().splitlines() if (m := re.match(r"^([A-Z_0-9]+)=", line))}


def test_every_settings_field_has_a_matching_env_example_entry():
    """Every env var app.config.Settings actually reads must be discoverable in
    .env.example -- this is exactly the kind of gap a user hit for a BYOK provider
    key (not a Settings field, so not what this test covers, but the same failure
    mode: an env var the app uses silently missing from .env.example)."""
    declared = _declared_keys(REPO_ROOT / ".env.example")
    missing = {name.upper() for name in Settings.model_fields} - declared
    assert missing == set()


def test_dormant_byok_provider_keys_are_documented_in_env_example():
    """LiteLLM picks these up directly from the process environment (see
    runtime_config.py) with no Settings field of their own -- .env.example is the
    only place that documents them for an operator at all, so a provider this repo
    names as supported (CLAUDE.md/README) must have its key placeholder here."""
    declared = _declared_keys(REPO_ROOT / ".env.example")
    assert {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"} <= declared


def test_k8s_env_example_mirrors_the_root_ones_secret_bearing_byok_keys():
    """k8s/base/.env.k8s.example's own header comment says it mirrors the root
    .env.example's secret-bearing vars -- keep that promise enforced, not just
    documented, so a key added to one and not the other (what actually happened
    with GEMINI_API_KEY) fails CI instead of surfacing as a user-reported bug."""
    declared = _declared_keys(REPO_ROOT / "k8s" / "base" / ".env.k8s.example")
    assert {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"} <= declared
