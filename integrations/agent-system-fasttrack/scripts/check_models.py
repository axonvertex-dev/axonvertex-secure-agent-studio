#!/usr/bin/env python3
import os
from common import load_env, models
load_env()
for n in 'ABC':
 try:
  d=models(os.environ[f'NODE_{n}_URL'],os.environ[f'NODE_{n}_API_KEY']); ids=[x.get('id') for x in d.get('data',[])]
  print(f'NODE {n}: OK configured={os.environ[f"NODE_{n}_MODEL"]} advertised={ids}')
 except Exception as e: print(f'NODE {n}: FAIL {type(e).__name__}: {e}')
