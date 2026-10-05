#!/usr/bin/env python3
import json, os
from pathlib import Path
from common import load_env, call, save
ROOT=Path(__file__).resolve().parents[1]
load_env()
case=json.loads((ROOT/'cases/security_case.json').read_text())
prompt=(
    "Analyze only supplied evidence. Return concise JSON with: primary_finding, cwe, confidence, "
    "source_to_sink, authentication, authorization, ssrf, xss, cluster_compromise, positive_controls, "
    "missing_evidence, remediation, regression_tests, unsupported_conclusions. Do not infer router "
    "registration bypasses middleware. Do not invent controls. Use CWE-78 for OS command injection "
    "when untrusted input reaches shell execution. CASE:\n" + json.dumps(case, indent=2)
)
runs={}
for n,label,mt in [('A','gemma',6000),('B','antares',1400),('C','foundation',2200)]:
    print(f'===== NODE {n} / {label} =====', flush=True)
    r=call(
        os.environ[f'NODE_{n}_URL'], os.environ[f'NODE_{n}_API_KEY'], os.environ[f'NODE_{n}_MODEL'],
        [
            {'role':'system','content':'You are a defensive application-security analyst. Separate observation from inference and refuse unsupported conclusions.'},
            {'role':'user','content':prompt}
        ],
        mt
    )
    runs[n]=r
    print('HTTP',r['http_status'],'elapsed',r['elapsed_seconds'],'finish',r['finish_reason'],
          'completion',r['usage'].get('completion_tokens'),'reasoning',bool(r['reasoning_content']))
p=save('common-security-benchmark',{'case':case['name'],'runs':runs})
print('RESULT',p)
