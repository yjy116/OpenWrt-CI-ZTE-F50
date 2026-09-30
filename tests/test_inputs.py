import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from inputs import validate_package_lock, verify_blob
from updater import KEEP_LINE, REPOSITORY_LINE, make_updater


def package_lock():
    blob = {'name': 'test.apk', 'sha256': 'a' * 64, 'size': 3, 'package': 'test', 'version': '1-r1'}
    return {'complete': True, 'packages': [blob],
            'keys': [{'name': 'public.pem', 'sha256': 'b' * 64, 'size': 5}],
            'required_packages': ['test'], 'excluded_packages': ['adguardhome'], 'remove_packages': [],
            'expected_inventory': {'test': '1-r1'}}


class InputTests(unittest.TestCase):
    def test_exact_blob_and_modified_blob_are_distinguished(self):
        payload = b'public fixture'
        spec = {'name': 'rootfs.tar.gz', 'size': len(payload),
                'sha256': hashlib.sha256(payload).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / spec['name']
            path.write_bytes(payload)
            verify_blob(path, spec)
            path.write_bytes(b'private fixture')
            with self.assertRaises(ValueError):
                verify_blob(path, spec)

    def test_missing_final_lock_and_forbidden_packages_fail(self):
        lock = package_lock()
        validate_package_lock(lock)
        for complete, name in [(False, 'test'), (True, 'adguardhome'), (True, 'kmod-tun')]:
            changed = package_lock()
            changed['complete'] = complete
            changed['packages'][0]['package'] = name
            changed['required_packages'] = [name]
            with self.assertRaises(ValueError):
                validate_package_lock(changed)

    def test_unsafe_input_names_and_versions_fail(self):
        for field, value in [('name', '../device-backup.apk'), ('version', '1\nrun-command')]:
            lock = package_lock()
            lock['packages'][0][field] = value
            with self.assertRaises(ValueError):
                validate_package_lock(lock)

    def test_unsigned_official_package_requires_matching_signed_index(self):
        lock = package_lock()
        lock['packages'][0]['feed'] = 'base'
        with self.assertRaises(ValueError):
            validate_package_lock(lock)
        lock['indexes'] = [{'feed': 'base', 'name': 'base-packages.adb',
                            'sha256': 'c' * 64, 'size': 20}]
        validate_package_lock(lock)
        lock['indexes'][0]['feed'] = '../base'
        with self.assertRaises(ValueError):
            validate_package_lock(lock)

    def test_final_inventory_rejects_missing_or_mismatched_requested_version(self):
        for inventory in ({}, {'test': '2-r1'}, {'test': '1-r1', 'adguardhome': '1-r1'}):
            lock = package_lock()
            lock['expected_inventory'] = inventory
            with self.assertRaises(ValueError):
                validate_package_lock(lock)

    def test_updater_patch_only_changes_repository_and_explicit_keep_paths(self):
        source = '#!/bin/sh\n' + REPOSITORY_LINE + '\n' + KEEP_LINE + '\n# other logic stays\n'
        options = {'repository': 'example/f50-ci', 'paths': ['etc/tailscale', 'etc/openclash']}
        result = make_updater(source, options)
        self.assertIn('MU300_REPO:-example/f50-ci', result)
        self.assertIn(' root etc/tailscale etc/openclash"', result)
        self.assertTrue(result.endswith('# other logic stays\n'))
        with self.assertRaises(ValueError):
            make_updater(source.replace(KEEP_LINE, ''), options)
        with self.assertRaises(ValueError):
            make_updater(source, dict(options, paths=['../device']))


if __name__ == '__main__':
    unittest.main()
