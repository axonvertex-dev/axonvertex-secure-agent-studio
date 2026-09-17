from __future__ import annotations

from dataclasses import dataclass

import yaml

from .config import PROJECT_ROOT


PROFILE_PATH = (
    PROJECT_ROOT
    / "benchmarks"
    / "config"
    / "context-profiles.yaml"
)


@dataclass(frozen=True)
class ContextProfile:
    name: str
    context_ceiling: int
    output_reserve: int
    safety_margin_tokens: int
    target_prompt_tokens: int

    @property
    def hard_prompt_limit(self) -> int:
        return (
            self.context_ceiling
            - self.output_reserve
        )

    @property
    def safe_prompt_limit(self) -> int:
        return (
            self.hard_prompt_limit
            - self.safety_margin_tokens
        )


def load_context_profiles() -> dict[str, ContextProfile]:
    with PROFILE_PATH.open(
        "r",
        encoding="utf-8",
    ) as handle:
        payload = yaml.safe_load(handle)

    result: dict[str, ContextProfile] = {}

    for name, config in payload["profiles"].items():
        profile = ContextProfile(
            name=name,
            context_ceiling=int(
                config["context_ceiling"]
            ),
            output_reserve=int(
                config["output_reserve"]
            ),
            safety_margin_tokens=int(
                config["safety_margin_tokens"]
            ),
            target_prompt_tokens=int(
                config["target_prompt_tokens"]
            ),
        )

        if (
            profile.target_prompt_tokens
            > profile.safe_prompt_limit
        ):
            raise ValueError(
                f"{name}: target_prompt_tokens "
                f"({profile.target_prompt_tokens}) exceeds "
                f"safe_prompt_limit "
                f"({profile.safe_prompt_limit})"
            )

        result[name] = profile

    return result
