"""One transport probe, not a benchmark sample. No repository or reference input."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    child_env = os.environ.copy()
    # Point the CLI at the user's existing login; never open/copy authentication material.
    child_env['CODEX_HOME'] = str(args.codex_home.resolve())
    command = [shutil.which('codex') or 'codex', 'exec', '--ignore-user-config', '--strict-config', '--ephemeral',
               '--skip-git-repo-check', '--sandbox', 'read-only', '--json', '--model', args.model,
               '--cd', str(root)]
    overrides = {'model_reasoning_effort': 'high', 'web_search': 'disabled',
                 'project_doc_max_bytes': 0,
                 'log_dir': (root/'logs').as_posix(), 'sqlite_home': (root/'state').as_posix()}
    for feature in ('shell_tool', 'shell_snapshot', 'unified_exec', 'multi_agent', 'apps', 'plugins', 'memories', 'hooks'):
        overrides['features.'+feature] = False
    for key, value in overrides.items():
        command += ['-c', key+'='+json.dumps(value)]
    command += ['-']
    prompt = 'Transport probe only. Do not call any tool. Return exactly the JSON object {"ready":true}.'
    (root/'request.json').write_text(json.dumps({'command': command, 'prompt': prompt}, indent=2), encoding='utf-8')
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', env=child_env)
    try:
        stdout, stderr = process.communicate(prompt, timeout=60)
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
        else:
            process.kill()
        stdout, stderr = process.communicate()
        stderr += '\nPROBE_TIMEOUT'
    (root/'stdout.jsonl').write_text(stdout, encoding='utf-8')
    (root/'stderr.txt').write_text(stderr, encoding='utf-8')
    print('exit', process.returncode)
    print(stdout[-6000:])
    print(stderr[-2000:])
    return process.returncode


if __name__ == '__main__':
    raise SystemExit(main())
