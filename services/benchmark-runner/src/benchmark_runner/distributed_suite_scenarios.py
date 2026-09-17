from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceRecord:
    position: float
    evidence_id: str
    text: str


@dataclass(frozen=True)
class ReasoningScenario:
    scenario_id: str
    description: str
    question: str
    expected_verdict: str
    expected_evidence_ids: frozenset[str]
    allowed_evidence_ids: frozenset[str]

    expected_counter_evidence_ids: frozenset[str]
    allowed_counter_evidence_ids: frozenset[str]

    expected_uncertainty_evidence_ids: frozenset[str]
    allowed_uncertainty_evidence_ids: frozenset[str]

    records: tuple[EvidenceRecord, ...]


SCENARIOS: dict[str, ReasoningScenario] = {
    "A-vulnerable": ReasoningScenario(
        scenario_id="A-vulnerable",
        description=(
            "Production disables JWT signature verification and "
            "authorization trusts the resulting role claim."
        ),
        question=(
            "Can an attacker submit a JWT whose signature is not "
            "cryptographically verified, set role=admin in its claims, "
            "and thereby gain access to /api/admin/export?"
        ),
        expected_verdict="VULNERABLE",
        expected_evidence_ids=frozenset({
            "A1", "A3", "A4", "A5", "A6",
        }),
        allowed_evidence_ids=frozenset({
            "A1", "A3", "A4", "A5", "A6",
        }),

        expected_counter_evidence_ids=frozenset({
            "AC1",
        }),
        allowed_counter_evidence_ids=frozenset({
            "AC1",
        }),

        expected_uncertainty_evidence_ids=frozenset(),
        allowed_uncertainty_evidence_ids=frozenset(),
        records=(
            EvidenceRecord(
                0.08,
                "A1",
                (
                    "EVIDENCE A1 | "
                    "route=/api/admin/export | "
                    "authentication=middleware.jwt_required | "
                    "authorization=authorize_role('admin') | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.24,
                "AC1",
                (
                    "COUNTER_EVIDENCE AC1 | "
                    "component=jwt-library-default | "
                    "JWT_VERIFY_SIGNATURE=true | "
                    "scope=library-default | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.48,
                "A3",
                (
                    "EVIDENCE A3 | "
                    "environment=production | "
                    "JWT_VERIFY_SIGNATURE=false | "
                    "precedence=runtime-production-override-"
                    "supersedes-library-default | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.64,
                "A4",
                (
                    "EVIDENCE A4 | "
                    "component=middleware.jwt_required | "
                    "behavior=when-JWT_VERIFY_SIGNATURE-is-false-"
                    "token-payload-is-decoded-and-claims-are-passed-"
                    "downstream-without-cryptographic-signature-"
                    "verification | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.78,
                "A5",
                (
                    "EVIDENCE A5 | "
                    "component=authorize_role | "
                    "behavior=authorization-allows-request-when-"
                    "decoded-claims-role-equals-required-role | "
                    "required_role=admin | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.91,
                "A6",
                (
                    "EVIDENCE A6 | "
                    "route=/api/admin/export | "
                    "additional-admin-verification=none | "
                    "server-side-admin-directory-lookup=none | "
                    "classification=authoritative"
                ),
            ),
        ),
    ),

    "B-not-vulnerable": ReasoningScenario(
        scenario_id="B-not-vulnerable",
        description=(
            "An insecure lower-precedence setting exists, but the "
            "production deployment policy enables mandatory signature "
            "verification before authorization."
        ),
        question=(
            "Can an attacker use an unsigned JWT containing role=admin "
            "to gain access to /api/admin/export?"
        ),
        expected_verdict="NOT_VULNERABLE",
        expected_evidence_ids=frozenset({
            "B1", "B3", "B4", "B5", "B6",
        }),
        allowed_evidence_ids=frozenset({
            "B1", "B3", "B4", "B5", "B6",
        }),

        expected_counter_evidence_ids=frozenset({
            "BC1",
        }),
        allowed_counter_evidence_ids=frozenset({
            "BC1",
        }),

        expected_uncertainty_evidence_ids=frozenset(),
        allowed_uncertainty_evidence_ids=frozenset(),
        records=(
            EvidenceRecord(
                0.08,
                "B1",
                (
                    "EVIDENCE B1 | "
                    "route=/api/admin/export | "
                    "authentication=middleware.jwt_required | "
                    "authorization=authorize_role('admin') | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.23,
                "BC1",
                (
                    "COUNTER_EVIDENCE BC1 | "
                    "source=base-container-configuration | "
                    "JWT_VERIFY_SIGNATURE=false | "
                    "precedence=lower-than-production-deployment-policy | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.46,
                "B3",
                (
                    "EVIDENCE B3 | "
                    "environment=production | "
                    "JWT_VERIFY_SIGNATURE=true | "
                    "precedence=production-deployment-policy-"
                    "supersedes-base-container-configuration | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.64,
                "B4",
                (
                    "EVIDENCE B4 | "
                    "component=middleware.jwt_required | "
                    "behavior=when-JWT_VERIFY_SIGNATURE-is-true-"
                    "requests-with-missing-or-invalid-signatures-are-"
                    "rejected-before-claims-are-passed-downstream | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.79,
                "B5",
                (
                    "EVIDENCE B5 | "
                    "component=authorize_role | "
                    "behavior=role-authorization-occurs-only-after-"
                    "jwt_required-successfully-verifies-token | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.91,
                "B6",
                (
                    "EVIDENCE B6 | "
                    "route=/api/admin/export | "
                    "authentication-bypass=none | "
                    "alternate-unsigned-token-path=none | "
                    "classification=authoritative"
                ),
            ),
        ),
    ),

    "C-insufficient": ReasoningScenario(
        scenario_id="C-insufficient",
        description=(
            "JWT signature verification is disabled, but authoritative "
            "evidence describing how authorize_role determines admin "
            "status is unavailable."
        ),
        question=(
            "Does an unsigned JWT containing role=admin necessarily "
            "allow an attacker to access /api/admin/export?"
        ),
        expected_verdict="INSUFFICIENT_EVIDENCE",
        expected_evidence_ids=frozenset({
            "C1", "C2", "C3",
        }),
        allowed_evidence_ids=frozenset({
            "C1", "C2", "C3",
        }),

        expected_counter_evidence_ids=frozenset(),
        allowed_counter_evidence_ids=frozenset(),

        expected_uncertainty_evidence_ids=frozenset({
            "C4",
        }),
        allowed_uncertainty_evidence_ids=frozenset({
            "CC1", "C4",
        }),

        records=(
            EvidenceRecord(
                0.08,
                "C1",
                (
                    "EVIDENCE C1 | "
                    "route=/api/admin/export | "
                    "authentication=middleware.jwt_required | "
                    "authorization=authorize_role('admin') | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.28,
                "C2",
                (
                    "EVIDENCE C2 | "
                    "environment=production | "
                    "JWT_VERIFY_SIGNATURE=false | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.49,
                "C3",
                (
                    "EVIDENCE C3 | "
                    "component=middleware.jwt_required | "
                    "behavior=when-signature-verification-is-disabled-"
                    "decoded-jwt-claims-are-made-available-downstream | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.68,
                "CC1",
                (
                    "EVIDENCE CC1 | "
                    "source=security-architecture-standard | "
                    "requirement=privileged-authorization-should-use-"
                    "server-side-identity-directory | "
                    "implementation-conformance=unknown | "
                    "classification=authoritative"
                ),
            ),
            EvidenceRecord(
                0.90,
                "C4",
                (
                    "EVIDENCE C4 | "
                    "source=repository-evidence-inventory | "
                    "authorize_role-implementation=not-available | "
                    "server-side-admin-directory-lookup-status=unknown | "
                    "jwt-role-claim-trust-status=unknown | "
                    "classification=authoritative"
                ),
            ),
        ),
    ),
}
