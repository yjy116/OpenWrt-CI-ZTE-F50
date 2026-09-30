"""Reviewed UI and executable overlays must preserve bytes and exact modes."""
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from overlay import OVERLAY_FILES, audit_overlay, stage_overlay


def make_sources(root):
    for name in OVERLAY_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())


LED_SCRIPT = 'opt/mu300/bin/mu300-led'


def make_tar(path, *, changed=False, led_mode=0o755):
    with tarfile.open(path, 'w:gz') as archive:
        for name in OVERLAY_FILES:
            payload = name.encode() + (b'changed' if changed else b'')
            member = tarfile.TarInfo('./' + name)
            member.mode = led_mode if name == LED_SCRIPT else 0o644
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))


class OverlayTests(unittest.TestCase):
    def test_only_reviewed_files_may_enter_the_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / 'files', root / 'staged'
            make_sources(source)
            records = stage_overlay(source, destination)
            self.assertEqual(set(records), set(OVERLAY_FILES))
            (source / 'unexpected-file').write_bytes(b'unexpected')
            with self.assertRaises(ValueError):
                stage_overlay(source, destination)

    def test_final_rootfs_overlay_must_match_staged_source_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_sources(root / 'files')
            records = stage_overlay(root / 'files', root / 'staged')
            archive = root / 'rootfs.tar.gz'
            make_tar(archive)
            audit_overlay(archive, records)
            make_tar(archive, changed=True)
            with self.assertRaises(ValueError):
                audit_overlay(archive, records)

    def test_led_script_is_staged_as_executable_and_cannot_lose_execute_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_sources(root / 'files')
            records = stage_overlay(root / 'files', root / 'staged')
            self.assertIn(LED_SCRIPT, records)
            self.assertEqual(records[LED_SCRIPT]['mode'], 0o755)
            archive = root / 'rootfs.tar.gz'
            make_tar(archive, led_mode=0o644)
            with self.assertRaises(ValueError):
                audit_overlay(archive, records)

    def test_overlay_audit_rejects_unreviewed_mode_in_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_sources(root / 'files')
            records = stage_overlay(root / 'files', root / 'staged')
            records[next(iter(records))]['mode'] = 0o777
            archive = root / 'rootfs.tar.gz'
            make_tar(archive)
            with self.assertRaises(ValueError):
                audit_overlay(archive, records)


if __name__ == '__main__':
    unittest.main()
