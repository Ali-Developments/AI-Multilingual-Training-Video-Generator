import os
import re
from pathlib import Path

secrets_found = []
ignore_dirs = {'.venv', '.sadtalker-venv', '.git', 'storage', '__pycache__', 'tools', '.pytest_cache', 'AI-Multilingual-Training-Video-Generator'}

pattern = re.compile(r'(gsk_[a-zA-Z0-9_-]{20,}|HEYGEN_API_KEY\s*=\s*[\'"][a-zA-Z0-9_-]{20,}[\'"])')

for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in ignore_dirs]
    for file in files:
        if file.endswith(('.py', '.md', '.json', '.txt', '.ini', '.ps1', '.yaml', '.yml')) and not file.startswith('.env'):
            fp = Path(root) / file
            try:
                content = fp.read_text(encoding='utf-8', errors='ignore')
                matches = pattern.findall(content)
                for m in matches:
                    if '1234567890abcdef' in m or 'abc1234567890' in m or '[REDACTED]' in m:
                        continue
                    secrets_found.append((str(fp), m[:8] + '...'))
            except Exception:
                pass

if secrets_found:
    print('WARNING: Secrets found!')
    for s in secrets_found:
        print(s)
else:
    print('SECRET SCAN PASSED: Zero real secrets detected in code/docs.')
