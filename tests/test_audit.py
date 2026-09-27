import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('audit', Path(__file__).parents[1] / 'scripts/audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def report(self, name='old', line=1):
        return json.dumps({'issues': [{'file': 'src/item.ts', 'exports': [{'name': name, 'line': line}]}]})

    def test_moving_lines_does_not_change_an_exception(self):
        self.assertEqual(audit.knip_findings(self.report(line=1), 'all'), audit.knip_findings(self.report(line=100), 'all'))

    def test_new_and_removed_findings_are_both_reported(self):
        old = audit.knip_findings(self.report(), 'all')
        new = audit.knip_findings(self.report('new'), 'all')
        added, stale = audit.compare(new, old)
        self.assertEqual(added[0][-1], 'new')
        self.assertEqual(stale[0][-1], 'old')

    def test_test_only_module_is_distinct_from_all_mode(self):
        self.assertNotEqual(audit.knip_findings(self.report(), 'all'), audit.knip_findings(self.report(), 'production'))

    def test_invalid_or_changed_scanner_output_fails(self):
        for raw in ['crashed', '{}', '{"issues": [{"file":"x", "exports":[{}]}]}']:
            with self.subTest(raw=raw), self.assertRaises(audit.ScanError):
                audit.knip_findings(raw, 'all')

    def test_tool_crash_is_not_treated_as_a_clean_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(audit.ScanError, 'exited 2'):
                audit.run(['python3', '-c', 'raise SystemExit(2)'], root, root, 'broken', {0, 1})

    def test_exceptions_require_reasons_and_unique_identities(self):
        entry = dict(zip(('tool', 'mode', 'file', 'kind', 'name'), ['knip', 'all', 'x', 'exports', 'y']))
        with self.assertRaisesRegex(audit.ScanError, 'reason'):
            audit.exceptions({'version': 1, 'findings': [entry]})
        entry['reason'] = 'Public runtime registration.'
        with self.assertRaisesRegex(audit.ScanError, 'Duplicate'):
            audit.exceptions({'version': 1, 'findings': [entry, entry]})

    def test_vulture_paths_are_portable_and_errors_are_not_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test.py').write_text('def first(**args):\n    pass\ndef second(**args):\n    pass\n')
            raw = '\n'.join(f"{root}/test.py:{line}: unused variable 'args' (100% confidence)" for line in [1, 3])
            found = audit.vulture_findings(raw, root)
            self.assertEqual(len(found), 2)
            self.assertEqual({item[-1] for item in found}, {"first: unused variable 'args'", "second: unused variable 'args'"})
            self.assertEqual({item[2] for item in found}, {'test.py'})
        with self.assertRaises(audit.ScanError):
            audit.vulture_findings('SyntaxError: broken', Path('/repo'))

    def test_duplicate_exports_have_stable_order(self):
        def report(names):
            return json.dumps({'issues': [{'file': 'x', 'duplicates': [[{'name': name} for name in names]]}]})
        self.assertEqual(audit.knip_findings(report(['a', 'b']), 'all'), audit.knip_findings(report(['b', 'a']), 'all'))


if __name__ == '__main__':
    unittest.main()
