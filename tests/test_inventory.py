"""Host-side full APK inventory acceptance, independent of target diff utilities."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from inventory import verify_installed_inventory


class InventoryTests(unittest.TestCase):
    def test_exact_full_inventory_allows_only_order_difference(self):
        verify_installed_inventory('luci-base-2-r1\nbusybox-1-r1\n',
                                   {'busybox': '1-r1', 'luci-base': '2-r1'})

    def test_missing_extra_changed_version_and_duplicate_lines_fail(self):
        expected = {'busybox': '1-r1', 'luci-base': '2-r1'}
        for actual in ('busybox-1-r1\n', 'busybox-1-r1\nluci-base-2-r1\nextra-1-r1\n',
                       'busybox-2-r1\nluci-base-2-r1\n',
                       'busybox-1-r1\nluci-base-2-r1\nluci-base-2-r1\n'):
            with self.subTest(actual=actual), self.assertRaisesRegex(ValueError, 'inventory differs'):
                verify_installed_inventory(actual, expected)


if __name__ == '__main__':
    unittest.main()
