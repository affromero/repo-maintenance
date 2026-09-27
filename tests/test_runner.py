import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for file in ['package.json', 'knip.json']:
            (self.root / file).write_text('{}')
        subprocess.run(['git', 'add', 'package.json', 'knip.json'], cwd=self.root, check=True)
        self.knip = self.root / 'node_modules/.bin/knip'
        self.knip.parent.mkdir(parents=True)
        self.exceptions = {'version': 1, 'findings': []}

    def scanner(self, name=None, status=None):
        report = {'issues': [] if name is None else [{'file': 'src/item.ts', 'exports': [{'name': name}]}]}
        code = int(name is not None) if status is None else status
        self.knip.write_text(f'#!/usr/bin/env python3\nprint({json.dumps(report)!r})\nraise SystemExit({code})\n')
        self.knip.chmod(0o755)

    def run_audit(self):
        (self.root / '.maintenance-exceptions.json').write_text(json.dumps(self.exceptions))
        return subprocess.run(['python3', str(ROOT / 'scripts/audit.py'), '--root', str(self.root)], capture_output=True, text=True)

    def test_new_findings_fail_until_reviewed_and_removed_findings_require_cleanup(self):
        self.scanner('unused')
        result = self.run_audit()
        self.assertEqual(result.returncode, 1, result.stderr)
        findings = json.loads((self.root / '.maintenance-reports/findings.json').read_text())
        self.assertEqual(len(findings), 2)
        self.exceptions['findings'] = [{**item, 'reason': 'Public entry consumed outside this repository.'} for item in findings]
        self.assertEqual(self.run_audit().returncode, 0)
        self.scanner()
        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn('2 stale exceptions', result.stdout)

    def test_tool_status_cannot_contradict_its_report(self):
        for name, code in [(None, 1), ('unused', 0), (None, 2)]:
            with self.subTest(name=name, code=code):
                self.scanner(name, code)
                result = self.run_audit()
                self.assertEqual(result.returncode, 2)
                self.assertTrue((self.root / '.maintenance-reports/error.txt').is_file())


spec = importlib.util.spec_from_file_location('update_tools', ROOT / 'scripts/update_tools.py')
update_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_tools)


class UpdaterTests(unittest.TestCase):
    def test_update_skips_yanked_prerelease_and_recent_versions(self):
        from datetime import datetime, timezone
        releases = [
            {'num': version, 'yanked': yanked, 'created_at': date}
            for version, yanked, date in [
                ('0.9.2', False, '2026-01-01T00:00:00Z'),
                ('0.10.0', False, '2026-01-01T00:00:00Z'),
                ('0.11.0', False, '2026-09-26T00:00:00Z'),
                ('1.0.0', True, '2026-01-01T00:00:00Z'),
                ('2.0.0-beta', False, '2026-01-01T00:00:00Z'),
            ]
        ]
        self.assertEqual(update_tools.newest_stable(releases, datetime(2026, 9, 27, tzinfo=timezone.utc)), '0.10.0')
