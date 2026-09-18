# Checkpoint 2C — Consolidated Findings

## Results

- Original strict baseline: **5/12 PASS**
- Decision Contract v2 raw: **9/12 PASS**
- Decision Contract v2 compacted: **9/9 PASS**
- Raw full audit citation complete: **4/12**
- Compacted full audit citation complete: **0/9**

## Failure classes

- `MISSING_REQUIRED_PROVENANCE`: 4
- `PROVENANCE_CONTRACT_FAILURE`: 4
- `SEMANTIC_VERDICT_FAILURE`: 3
- `TRACE_VERDICT_CONTRADICTION`: 3

## Main finding

Raw long-context causal reasoning passed 9/12 cases.
The three remaining failures were C-insufficient at 64K, 96K, and 128K.

Evidence-preserving deterministic compaction rescued all nine tested 64K-128K causal decisions.

A6 and B6 are closure/audit evidence rather than indispensable causal links.
C4 is decision-critical uncertainty and must constrain the verdict.

Evidence visibility, reasoning correctness, model citation completeness, and system audit provenance must therefore be evaluated separately.

## Architectural implication

Complete provenance belongs to the Evidence Decision Graph / control plane.
The reasoning model may operate on a causally sufficient subset while the system retains the complete evidence inventory.

Checkpoint 2D will compare explicit reasoning effort against context compaction.
