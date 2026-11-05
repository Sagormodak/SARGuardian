"""Rebuild target workflows from preserved Git objects, retaining scientific pins.

Run from a full clone with archive tags fetched. Requires PyYAML.
"""
from pathlib import Path
import copy
import json
import re
import subprocess
import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / 'docs/migration/source-manifest.json').read_text())
SOURCES = MANIFEST['sources']
REPOS = {SOURCES[k]['repository']: k for k in ('dynamic', 'backend', 'science')}
REPOS['Sagormodak/SARGuardian'] = 'science'  # Historical science fork, identical pinned objects.

class Loader(yaml.SafeLoader):
    pass

# GitHub uses YAML 1.2: "on" is a key, not a boolean.
Loader.yaml_implicit_resolvers = copy.deepcopy(Loader.yaml_implicit_resolvers)
for char, values in Loader.yaml_implicit_resolvers.items():
    Loader.yaml_implicit_resolvers[char] = [(tag, rx) for tag, rx in values if tag != 'tag:yaml.org,2002:bool']
Loader.add_implicit_resolver('tag:yaml.org,2002:bool', re.compile(r'^(?:true|false)$', re.I), list('tTfF'))

class Dumper(yaml.SafeDumper):
    pass

def represent_string(dumper, value):
    return dumper.represent_scalar('tag:yaml.org,2002:str', value, style='|' if '\n' in value else None)
Dumper.add_representer(str, represent_string)

def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args]).decode('utf-8')

def resolve(key, ref):
    if re.fullmatch(r'[0-9a-f]{40}', ref):
        git('cat-file', '-e', ref + '^{commit}')
        return ref
    for kind in ('heads', 'tags'):
        try:
            return git('rev-parse', '--verify', f'refs/tags/archive/{key}/{kind}/{ref}^{{commit}}').strip()
        except subprocess.CalledProcessError:
            pass
    raise ValueError(f'Unresolved source ref: {key}/{ref}')

mapping = {}
used = set()
records = []
pins = set()
out = ROOT / '.github/workflows'
out.mkdir(parents=True, exist_ok=True)

def pin(key, sha):
    pins.add((key, sha))

def import_workflow(key, sha, path, preferred=None):
    identity = (key, sha, path)
    if identity in mapping:
        return mapping[identity]
    name = preferred or Path(path).name
    if name in used:
        name = f'{key}-{Path(path).stem}-{sha[:8]}.yml'
    used.add(name)
    mapping[identity] = name
    raw = git('show', f'{sha}:{path}')
    data = yaml.load(raw, Loader=Loader)
    original = copy.deepcopy(data)
    pin(key, sha)
    record = {'source': key, 'sha': sha, 'source_path': path, 'target': f'.github/workflows/{name}',
              'original_triggers': original.get('on'), 'checkouts': [], 'reusable_calls': [], 'script_fixes': []}
    for job_name, job in data.get('jobs', {}).items():
        use = job.get('uses', '')
        if use.startswith('./.github/workflows/'):
            dep = import_workflow(key, sha, use[2:])
            job['uses'] = f'./.github/workflows/{dep}'
        elif '/.github/workflows/' in use:
            match = re.fullmatch(r'([^/]+/[^/]+)/(.+)@(.+)', use)
            repo, dep_path, ref = match.groups()
            if repo not in REPOS:
                raise ValueError(f'Unreviewed reusable repository: {repo}')
            dep_key = REPOS[repo]
            dep = import_workflow(dep_key, resolve(dep_key, ref), dep_path)
            job['uses'] = f'./.github/workflows/{dep}'
        if use:
            record['reusable_calls'].append({'job': job_name, 'before': use, 'after': job['uses']})
        for step_index, step in enumerate(job.get('steps', [])):
            if key == 'backend' and path.endswith('/river-shift-tests.yml') and 'run' in step:
                before_run = step['run']
                # Quote the literal expression in two Bash strings so GitHub
                # does not evaluate a nonexistent job_id input inside grep.
                step['run'] = before_run.replace("'run-name: RiverShift ${{ inputs.job_id }}'", "'run-name: RiverShift $''{{ inputs.job_id }}'")
                if step['run'] != before_run:
                    record['script_fixes'].append({'job': job_name, 'step': step_index, 'before': before_run, 'after': step['run']})
            if not step.get('uses', '').startswith('actions/checkout@'):
                continue
            settings = step.setdefault('with', {})
            before = copy.deepcopy(settings)
            repo = settings.get('repository')
            checkout_key = REPOS[repo] if repo in REPOS else key
            if repo and repo not in REPOS and repo != '${{ github.repository }}':
                raise ValueError(f'Unreviewed checkout repository: {repo}')
            ref = str(settings.get('ref', sha))
            if ref in ('${{ github.sha }}', '${{ github.ref }}'):
                ref = sha
            if '${{' not in ref:
                ref = resolve(checkout_key, ref)
                pin(checkout_key, ref)
            settings['repository'] = '${{ github.repository }}'
            settings['ref'] = ref
            record['checkouts'].append({'job': job_name, 'before': before, 'after': copy.deepcopy(settings), 'source': checkout_key})
    # Original automatic CI/replay triggers are preserved in the snapshots and
    # register. The target has one current-tree CI workflow; imported scientific
    # entrypoints are callable/manual only, preventing duplicate live dispatch.
    events = data.get('on', {})
    if isinstance(events, dict):
        events = {k: v for k, v in events.items() if k in ('workflow_call', 'workflow_dispatch')}
    else:
        events = {}
    if not events:
        events = {'workflow_dispatch': None}
    data['on'] = events
    record['target_triggers'] = events
    record['disposition'] = 'manual/reusable; original automatic triggers archived; current-tree CI centralized'
    (out / name).write_text('# Generated by scripts/centralize_workflows.py; scientific source SHAs are unchanged.\n' + yaml.dump(data, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=110), encoding='utf-8', newline='\n')
    records.append(record)
    return name

if __name__ == '__main__':
    for key in ('dynamic', 'backend', 'science'):
        source = SOURCES[key]
        names = git('ls-tree', '-r', '--name-only', source['sha'], '.github/workflows').splitlines()
        for path in names:
            if path.endswith(('.yml', '.yaml')):
                import_workflow(key, source['sha'], path)
    for key, sha in sorted(pins):
        git('update-ref', f'refs/tags/archive/{key}/pins/{sha}', sha)
    (ROOT / 'docs/migration/workflow-register.json').write_text(json.dumps(records, indent=2) + '\n', encoding='utf-8')
    (ROOT / 'docs/migration/workflow-pins.json').write_text(json.dumps([{'source': k, 'sha': s, 'tag': f'archive/{k}/pins/{s}'} for k, s in sorted(pins)], indent=2) + '\n', encoding='utf-8')
    print(f'Centralized {len(records)} workflows; retained {len(pins)} immutable source pins')
