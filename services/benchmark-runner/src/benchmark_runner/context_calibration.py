from __future__ import annotations

from .config import gemma_endpoint
from .context_profiles import load_context_profiles
from .token_counter import TokenCounter


SYSTEM = """
You are an AXONVERTEX Secure Agent Studio
long-context benchmark model.
Follow the user's final instruction exactly.
""".strip()


def main() -> None:
    endpoint = gemma_endpoint()
    profiles = load_context_profiles()

    counter = TokenCounter(endpoint)

    try:
        print(
            "=============================================="
        )
        print(
            " AXONVERTEX Secure Agent Studio"
        )
        print(
            " Checkpoint 2 — Context Profile Calibration"
        )
        print(
            "=============================================="
        )

        baseline = counter.count(
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content":
                        "Return exactly BASELINE_OK."
                }
            ],
        )

        print()
        print(
            f"Baseline formatted chat tokens: {baseline}"
        )
        print()

        for name, profile in profiles.items():
            available_payload = (
                profile.target_prompt_tokens
                - baseline
            )

            print(
                f"{name:>4} | "
                f"ceiling={profile.context_ceiling:>6} | "
                f"target_prompt={profile.target_prompt_tokens:>6} | "
                f"baseline={baseline:>4} | "
                f"payload_budget={available_payload:>6} | "
                f"output_reserve={profile.output_reserve:>5}"
            )

    finally:
        counter.close()


if __name__ == "__main__":
    main()
