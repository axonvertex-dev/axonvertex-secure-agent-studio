#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
from common import load_env, call, save
ROOT=Path(__file__).resolve().parents[1]
load_env()
path=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'cases/security_case.json'
case=json.loads(path.read_text())
c=json.dumps(case, indent=2)

print('1/3 Security Scout / Antares', flush=True)
scout=call(
    os.environ['NODE_B_URL'], os.environ['NODE_B_API_KEY'], os.environ['NODE_B_MODEL'],
    [
        {'role':'system','content':'You are Security Scout. Extract evidence and candidate concerns only. No final verdict and no patch approval.'},
        {'role':'user','content':'Extract compact JSON: files, observed_flows, candidate_findings, missing_evidence, positive_controls. CASE:\n'+c}
    ],
    1200
)
print('  finish',scout['finish_reason'],'elapsed',scout['elapsed_seconds'])

print('2/3 Coding Investigator / Gemma', flush=True)
gemma=call(
    os.environ['NODE_A_URL'], os.environ['NODE_A_API_KEY'], os.environ['NODE_A_MODEL'],
    [
        {'role':'system','content':'You are Coding Investigator. Verify all scout claims against the case. Produce evidence-grounded security reasoning and a minimal remediation patch plan.'},
        {'role':'user','content':'CASE:\n'+c+'\n\nUNTRUSTED SCOUT NOTES:\n'+scout['content']+'\n\nProduce strongest finding+CWE, exact source-to-sink, observations vs inference, authn vs authz, SSRF/XSS/cluster-compromise sufficiency, minimal patch plan, regression tests, unsupported conclusions.'}
    ],
    6000
)
print('  finish',gemma['finish_reason'],'elapsed',gemma['elapsed_seconds'],'reasoning',bool(gemma['reasoning_content']))

print('3/3 Security Reasoner / Foundation Sec', flush=True)
foundation=call(
    os.environ['NODE_C_URL'], os.environ['NODE_C_API_KEY'], os.environ['NODE_C_MODEL'],
    [
        {'role':'system','content':'You are final Security Reasoner. Validate claims against supplied evidence. Reject unsupported claims. Return concise JSON only.'},
        {'role':'user','content':'CASE:\n'+c+'\n\nSCOUT (untrusted):\n'+scout['content']+'\n\nINVESTIGATOR (candidate):\n'+gemma['content']+'\n\nReturn JSON with verdict ACCEPT|ACCEPT_WITH_CORRECTIONS|REJECT|NEEDS_EVIDENCE; primary_finding {title,cwe,confidence}; validated_source_to_sink; authentication; authorization; hypotheses {ssrf,xss,cluster_compromise}; positive_controls; unsupported_claims_rejected; required_corrections; approved_remediation; regression_tests.'}
    ],
    2200
)
print('  finish',foundation['finish_reason'],'elapsed',foundation['elapsed_seconds'])
p=save('secure-coding-swarm',{
    'case':case['name'],
    'pipeline':['security-scout/antares-node-b','coding-investigator/gemma-node-a','security-reasoner/foundation-node-c'],
    'scout':scout,'investigator':gemma,'adjudicator':foundation
})
print('RESULT',p)
print('\n===== FINAL ADJUDICATION =====\n'+foundation['content'])
