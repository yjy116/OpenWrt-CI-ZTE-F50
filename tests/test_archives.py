"""Release archive acceptance: protocol, traversal and private-device data."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def make_archive(path, files):
    with tarfile.open(path, 'w:gz') as archive:
        for name, payload in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(payload)
            entry.mode = 0o644
            archive.addfile(entry, io.BytesIO(payload))


class ArchiveTests(unittest.TestCase):
    def model(self):
        path = ROOT / 'scripts/archive_checks.py'
        self.assertTrue(path.is_file(), 'Release artifacts require a real content audit')
        spec = importlib.util.spec_from_file_location('archive_checks', path)
        model = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(model)
        return model

    def test_kernel_bundle_protocol_and_version_are_enforced(self):
        model = self.model()
        files = {'./Image': b'kernel', './ramdisk-generic.lz4': b'ramdisk',
                 './kernel.release': b'7.2.8-f50-dae1\n', './devices': b'f50\n',
                 './modules/test.ko': b'module', './modules.builtin': b'builtin',
                 './modules.builtin.modinfo': b'info'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'kernel.tar.gz'
            make_archive(path, files)
            model.audit_kernel(path, '7.2.8-f50-dae1')
            with self.assertRaises(ValueError):
                model.audit_kernel(path, '6.18.54-f50-dae1')
            del files['./devices']
            make_archive(path, files)
            with self.assertRaises(ValueError):
                model.audit_kernel(path, '7.2.8-f50-dae1')

    def test_traversal_duplicate_and_private_files_are_rejected(self):
        model = self.model()
        for name in ('../escape', '/absolute', './etc/dropbear/dropbear_rsa_host_key',
                     './var/lib/zerotier-one/identity.secret', './etc/tailscale/tailscaled.state',
                     './opt/mu300/android/vendor/lib64/private.so'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'rootfs.tar.gz'
                make_archive(path, {name: b'test'})
                with self.assertRaises(ValueError):
                    model.audit_rootfs(path)

    def test_machine_id_and_password_hashes_are_rejected(self):
        model = self.model()
        for name, payload in [('etc/machine-id', b'private-id'),
                              ('etc/shadow', b'root:$6$privatehash:0:0:0:0:::\n')]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'rootfs.tar.gz'
                make_archive(path, {name: payload})
                with self.assertRaises(ValueError):
                    model.audit_rootfs(path)

    def test_duplicate_member_cannot_override_earlier_audit(self):
        model = self.model()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'duplicate.tar.gz'
            with tarfile.open(path, 'w:gz') as archive:
                for name in ('./etc/test', 'etc/test'):
                    entry = tarfile.TarInfo(name)
                    archive.addfile(entry, io.BytesIO(b''))
            with self.assertRaises(ValueError):
                model.audit_rootfs(path)

    def test_luci_passwd_file_reference_is_not_an_account_password(self):
        model = self.model()
        model.check_sensitive_content('etc/config/luci', b"option passwd '/etc/passwd'\n")
        model.check_sensitive_content('etc/config/rpcd', b"option password '$p$root'\n")
        with self.assertRaises(ValueError):
            model.check_sensitive_content('etc/config/luci', b"option password 'private-value'\n")

    def test_links_keep_rootfs_symlinks_but_reject_archive_escape(self):
        model = self.model()
        member = tarfile.TarInfo('link')
        member.type = tarfile.SYMTYPE
        member.linkname = '/tmp/resolv.conf'
        model.validate_link(member, 'link')
        member.linkname = '..'
        with self.assertRaises(ValueError):
            model.validate_link(member, 'link')
        member.type = tarfile.LNKTYPE
        member.linkname = '/etc/shadow'
        with self.assertRaises(ValueError):
            model.validate_link(member, 'link')


if __name__ == '__main__':
    unittest.main()
