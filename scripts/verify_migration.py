"""Check lossless import, reviewed adaptations, archived refs and workflow contracts."""
from pathlib import Path
import copy
import hashlib
import json
import subprocess
import sys

from centralize_workflows import Loader
import yaml

ROOT = Path(__file__).resolve().parents[1]

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def main():
    manifest = json.loads((ROOT / 'docs/migration/source-manifest.json').read_text())
    changes = json.loads((ROOT / 'docs/migration/adaptations.json').read_text())
    adapted = {entry['path']: entry for entry in changes}
    changed = set()
    for entry in manifest['files']:
        path = ROOT / entry['path']
        require(path.is_file(), f'Missing imported file: {entry["path"]}')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        expected = entry['sha256']
        if entry['path'] in adapted:
            change = adapted[entry['path']]
            require(change['original_sha256'] == expected, f'Incorrect original hash: {path}')
            expected = change['sha256']
            changed.add(entry['path'])
        require(digest == expected, f'Unexpected source change: {entry["path"]}')
    require(set(adapted) == changed, 'Unknown adaptation paths')
    for entry in manifest['refs']:
        if entry.get('publication') == 'local-only':
            continue
        actual = git('rev-parse', '--verify', entry['target']).decode().strip()
        require(actual == entry['object'], f'Lost source history: {entry["target"]}')
    pins = json.loads((ROOT / 'docs/migration/workflow-pins.json').read_text())
    for entry in pins:
        require(git('rev-parse', entry['tag']).decode().strip() == entry['sha'], f'Lost science pin: {entry}')
    register = json.loads((ROOT / 'docs/migration/workflow-register.json').read_text())
    for entry in register:
        source = yaml.load(git('show', f'{entry["sha"]}:{entry["source_path"]}'), Loader=Loader)
        target = yaml.load((ROOT / entry['target']).read_text(encoding='utf-8'), Loader=Loader)
        expected = copy.deepcopy(source)
        expected['on'] = entry['target_triggers']
        for call in entry['reusable_calls']:
            expected['jobs'][call['job']]['uses'] = call['after']
        for fix in entry.get('script_fixes', []):
            require(expected['jobs'][fix['job']]['steps'][fix['step']]['run'] == fix['before'], 'Script-fix source mismatch')
            expected['jobs'][fix['job']]['steps'][fix['step']]['run'] = fix['after']
        for job in expected['jobs'].values():
            for step in job.get('steps', []):
                if step.get('uses', '').startswith('actions/checkout@'):
                    # Match by job and exact original checkout options, in order.
                    step.pop('with', None)
        actual = copy.deepcopy(target)
        for job in actual['jobs'].values():
            for step in job.get('steps', []):
                if step.get('uses', '').startswith('actions/checkout@'):
                    require(step.get('with', {}).get('repository') == '${{ github.repository }}', 'External source checkout')
                    step.pop('with', None)
        require(expected == actual, f'Workflow semantic drift: {entry["target"]}')
        observed = [(name, step.get('with')) for name, job in target['jobs'].items() for step in job.get('steps', []) if step.get('uses', '').startswith('actions/checkout@')]
        require(observed == [(item['job'], item['after']) for item in entry['checkouts']], f'Checkout pin drift: {entry["target"]}')
        for job in target['jobs'].values():
            use = job.get('uses', '')
            if use:
                require(use.startswith('./.github/workflows/'), f'External workflow dependency: {use}')
                require((ROOT / use).is_file(), f'Missing reusable workflow: {use}')
    render = yaml.load((ROOT / 'render.yaml').read_text(), Loader=Loader)
    for service in render['services']:
        require((ROOT / service['rootDir']).is_dir(), 'Invalid Render root')
    api = render['services'][0]
    env = {x['key']: x.get('value') for x in api['envVars']}
    for key in ('GITHUB_ACTIONS_REPOSITORY', 'RIVERSHIFT_GITHUB_ACTIONS_REPOSITORY', 'KNOWN_PLACE_REPOSITORY', 'KNOWN_PLACE_PAPER_REPOSITORY'):
        require(env[key] == manifest['destination'], f'Incorrect destination: {key}')
    published_refs = sum(entry.get('publication') != 'local-only' and entry['original'].startswith('refs/') for entry in manifest['refs'])
    print(f'PASS: {len(manifest["files"])} imported files, {len(changed)} reviewed adaptation(s), {published_refs} source history refs, {len(pins)} scientific pins, {len(register)} workflow contracts')

if __name__ == '__main__':
    main()
