"""Request header rewriting for proxy demonstrations."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from config.settings import HEADER_RULES_PATH


DEFAULT_HEADER_RULES: dict[str, Any] = {
    "enabled": True,
    "active_profile": "tenant",
    "set_headers": {
        "X-Proxy-Demo": "HouseRent-Cache-Proxy",
    },
    "remove_headers": [
        "X-Remove-Me",
    ],
    "profiles": {
        "tenant": {
            "X-Demo-Role": "tenant",
            "X-Client-Type": "tenant-browser",
        },
        "landlord": {
            "X-Demo-Role": "landlord",
            "X-Client-Type": "landlord-dashboard",
        },
        "admin": {
            "X-Demo-Role": "admin",
            "X-Client-Type": "admin-console",
        },
    },
}


class HeaderModifier:
    """Loads and applies configurable request header rewrite rules."""

    def __init__(self, file_path: str | Path = HEADER_RULES_PATH) -> None:
        self.file_path = Path(file_path)
        self._rules: dict[str, Any] = deepcopy(DEFAULT_HEADER_RULES)
        self.load()

    def load(self) -> dict[str, Any]:
        if not self.file_path.exists():
            self.save(DEFAULT_HEADER_RULES)
            return self.get_rules()

        with open(self.file_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        rules = deepcopy(DEFAULT_HEADER_RULES)
        rules.update(loaded)
        rules["set_headers"] = {
            **DEFAULT_HEADER_RULES["set_headers"],
            **loaded.get("set_headers", {}),
        }
        rules["profiles"] = {
            **DEFAULT_HEADER_RULES["profiles"],
            **loaded.get("profiles", {}),
        }
        self._rules = rules
        return self.get_rules()

    def save(self, rules: dict[str, Any] | None = None) -> dict[str, Any]:
        if rules is not None:
            merged = deepcopy(DEFAULT_HEADER_RULES)
            merged.update(rules)
            self._rules = merged

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self._rules, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return self.get_rules()

    def get_rules(self) -> dict[str, Any]:
        return deepcopy(self._rules)

    def set_active_profile(self, profile: str) -> dict[str, Any]:
        if profile not in self._rules.get("profiles", {}):
            raise ValueError(f"unknown header profile: {profile}")
        self._rules["active_profile"] = profile
        return self.save()

    def apply(self, headers: dict[str, str]) -> dict[str, str]:
        if not self._rules.get("enabled", True):
            return dict(headers)

        rewritten = dict(headers)

        for name in self._rules.get("remove_headers", []):
            rewritten.pop(str(name).lower(), None)

        for name, value in self._rules.get("set_headers", {}).items():
            rewritten[str(name).lower()] = str(value)

        active_profile = self._rules.get("active_profile")
        profile_headers = self._rules.get("profiles", {}).get(active_profile, {})
        for name, value in profile_headers.items():
            rewritten[str(name).lower()] = str(value)

        return rewritten


_header_modifier_instance: HeaderModifier | None = None


def get_header_modifier() -> HeaderModifier:
    global _header_modifier_instance
    if _header_modifier_instance is None:
        _header_modifier_instance = HeaderModifier()
    return _header_modifier_instance
