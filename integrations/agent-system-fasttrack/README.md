# AXONVERTEX Agent System — Fast Track E2E

Three-agent pipeline:
- Node B / Antares-1B = Security Scout
- Node A / Gemma-4-12B = Coding Investigator
- Node C / Foundation-Sec-8B = Security Reasoner

Run on Node B:
1. `bash scripts/bootstrap-secrets-node-b.sh`
2. `python3 scripts/check_models.py`
3. `python3 scripts/run_common_benchmark.py`
4. `python3 scripts/run_secure_coding_swarm.py cases/security_case.json`

The runner does not change the existing inference services or Agent Registry. It writes evidence JSON under `results/`. Raw API keys are kept only in `.env.agent-system` mode 600. Replace this temporary lab mechanism with SPIFFE/SPIRE before production.
