"""Run scanners without accepting new findings, stale exceptions, or tool errors."""

import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class ScanError(RuntimeError):
    pass


def finding(tool, mode, file, kind, name):
    return (tool, mode, file, kind, name)


def knip_findings(raw, mode):
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ScanError('Knip did not return valid JSON') from error
    if not isinstance(report, dict) or not isinstance(report.get('issues'), list):
        raise ScanError('Knip report is missing its issues array')
    findings = set()
    for issue in report['issues']:
        if not isinstance(issue, dict) or not isinstance(issue.get('file'), str):
            raise ScanError('Invalid Knip issue')
        for kind, entries in issue.items():
            if kind == 'file' or kind == 'owners':
                continue
            if not isinstance(entries, list):
                raise ScanError(f'Unknown Knip issue format: {kind}')
            for entry in entries:
                if kind == 'duplicates' and isinstance(entry, list):
                    name = ','.join(sorted(item['name'] for item in entry))
                elif isinstance(entry, dict) and isinstance(entry.get('name'), str):
                    name = entry['name']
                else:
                    raise ScanError(f'Invalid Knip finding: {kind}')
                findings.add(finding('knip', mode, issue['file'], kind, name))
    return findings


def vulture_findings(raw, root):
    findings = set()
    for line in raw.splitlines():
        match = re.fullmatch(r"(.+?):(\d+): (.+?) \((\d+)% confidence\)", line)
        if not match:
            raise ScanError(f'Unrecognized Vulture output: {line}')
        file, line_number, description, confidence = match.groups()
        path = Path(file)
        if path.is_absolute():
            try:
                file = path.relative_to(root).as_posix()
            except ValueError as error:
                raise ScanError('Vulture finding outside repository') from error
        tree = ast.parse((root / file).read_text())
        scopes = []
        def visit(node, parents):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                parents = [*parents, node.name]
                if node.lineno <= int(line_number) <= node.end_lineno:
                    scopes.append(parents)
            for child in ast.iter_child_nodes(node):
                visit(child, parents)
        visit(tree, [])
        scope = '.'.join(max(scopes, key=len)) if scopes else '<module>'
        findings.add(finding('vulture', 'all', file, 'unused', f'{scope}: {description}'))
    return findings


def exceptions(raw):
    if not isinstance(raw, dict) or raw.get('version') != 1:
        raise ScanError('Exceptions must use version 1')
    if not isinstance(raw.get('findings'), list):
        raise ScanError('Exceptions must contain findings')
    result = set()
    for entry in raw['findings']:
        if not isinstance(entry, dict) or not isinstance(entry.get('reason'), str) or not entry['reason'].strip():
            raise ScanError('Every exception needs a review reason')
        keys = ('tool', 'mode', 'file', 'kind', 'name')
        if any(not isinstance(entry.get(key), str) or not entry[key] for key in keys):
            raise ScanError('Every exception needs an exact finding identity')
        identity = tuple(entry[key] for key in keys)
        if identity in result:
            raise ScanError('Duplicate exception: ' + ' | '.join(identity))
        result.add(identity)
    return result


def compare(actual, expected):
    return sorted(actual - expected), sorted(expected - actual)


def run(command, root, reports, name, allowed):
    try:
        result = subprocess.run(command, cwd=root, text=True, capture_output=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ScanError(f'{name} could not run: {error}') from error
    (reports / f'{name}.stdout').write_text(result.stdout)
    (reports / f'{name}.stderr').write_text(result.stderr)
    if result.returncode not in allowed:
        raise ScanError(f'{name} exited {result.returncode}:\n{result.stderr}\n{result.stdout}')
    return result


def scan(root, reports):
    actual = set()
    tracked = run(['git', 'ls-files', '-z'], root, reports, 'tracked', {0}).stdout.split('\0')
    if 'package.json' in tracked:
        executable = root / 'node_modules/.bin/knip'
        if not executable.exists() or 'knip.json' not in tracked:
            raise ScanError('Node repositories require installed Knip and tracked knip.json')
        for mode, flags in [('all', []), ('production', ['--production', '--include', 'files'])]:
            result = run([str(executable), '--no-progress', '--reporter', 'json', *flags], root, reports, f'knip-{mode}', {0, 1})
            found = knip_findings(result.stdout, mode)
            if (result.returncode == 1) != bool(found):
                raise ScanError(f'Knip {mode} exit status disagrees with its findings')
            actual.update(found)
    python_files = [file for file in tracked if file.endswith('.py')]
    if python_files:
        requirement = (Path(__file__).resolve().parents[1] / 'requirements.txt').read_text().strip()
        if not re.fullmatch(r'vulture==[0-9.]+', requirement):
            raise ScanError('Expected an exact Vulture requirement')
        result = run(['uvx', '--from', requirement, 'vulture', '--min-confidence', '80', *python_files], root, reports, 'vulture', {0, 3})
        found = vulture_findings(result.stdout, root)
        if (result.returncode == 3) != bool(found):
            raise ScanError('Vulture exit status disagrees with its findings')
        actual.update(found)
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--report-only', action='store_true', help='Collect findings without updating exceptions. Not for CI.')
    args = parser.parse_args()
    root = args.root.resolve()
    reports = root / '.maintenance-reports'
    reports.mkdir(exist_ok=True)
    try:
        actual = scan(root, reports)
        serialized = [dict(zip(('tool', 'mode', 'file', 'kind', 'name'), row)) for row in sorted(actual)]
        (reports / 'findings.json').write_text(json.dumps(serialized, indent=2) + '\n')
        if args.report_only:
            print(f'Collected {len(actual)} findings. Exceptions were not changed.')
            return 0
        expected = exceptions(json.loads((root / '.maintenance-exceptions.json').read_text()))
        new, stale = compare(actual, expected)
        lines = [f'Dead-code audit: {len(new)} new findings, {len(stale)} stale exceptions.']
        for label, items in [('New findings', new), ('Stale exceptions', stale)]:
            if items:
                lines += ['', label, *(' | '.join(item) for item in items)]
        message = '\n'.join(lines) + '\n'
        (reports / 'summary.txt').write_text(message)
        print(message)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
                stream.write('```text\n' + message + '```\n')
        return int(bool(new or stale))
    except (ScanError, OSError, ValueError) as error:
        message = f'Dead-code audit failed: {error}\n'
        (reports / 'error.txt').write_text(message)
        print(message, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
