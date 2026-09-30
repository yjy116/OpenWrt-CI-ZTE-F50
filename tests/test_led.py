"""Run the shipped LED script against isolated sysfs files and radio inputs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'files/opt/mu300/bin/mu300-led'
COMMAND_TIMEOUT = 10
LED_VALUES = {
    'keyboard-backlight': (0, 127),
    'sc27xx:blue': (73, 255),
    'sc27xx:red': (21, 255),
    'sc27xx:green': (13, 255),
    'net_blue': (0, 255),
    'zte-ldo0': (0, 1),
    'zte-ldo1': (0, 1),
    'zte-ldo2': (0, 1),
}


def shell_path(path):
    value = str(path.resolve()).replace('\\', '/')
    return '/' + value[0].lower() + value[2:] if os.name == 'nt' else value


def write_executable(path, text):
    path.write_text(text, encoding='utf-8', newline='\n')
    path.chmod(0o755)


class LedTests(unittest.TestCase):
    def setUp(self):
        self.shell = os.environ.get('F50_TEST_SH') or shutil.which('sh')
        if not self.shell:
            raise RuntimeError('A POSIX shell is required; set F50_TEST_SH explicitly')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.leds = self.root / 'sys/class/leds'
        for name, (brightness, maximum) in LED_VALUES.items():
            directory = self.leds / name
            try:
                directory.mkdir(parents=True)
            except OSError as error:
                raise RuntimeError('LED tests require Linux filenames such as sc27xx:blue; use Linux CI') from error
            (directory / 'brightness').write_text(str(brightness))
            (directory / 'max_brightness').write_text(str(maximum))
            (directory / 'trigger').write_text('timer')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        write_executable(self.bin / 'mu300-device', '#!/bin/sh\nprintf "%s\\n" "$F50_TEST_DEVICE"\n')
        write_executable(self.bin / 'iw', '#!/bin/sh\nprintf "channel %s\\n" "$F50_TEST_CHANNEL"\n')
        self.environment = dict(os.environ, MU300_SYSROOT=shell_path(self.root),
                                MU300_BIN=shell_path(self.bin),
                                MU300_LED_CONF=shell_path(self.root / 'led.conf'))
        self.environment['PATH'] = shell_path(self.bin) + ':' + self.environment['PATH']
        (self.root / 'led.conf').write_text('LED_TIMEOUT=0\n')

    def run_led(self, *args, device='f50', channel=36):
        environment = dict(self.environment, F50_TEST_DEVICE=device, F50_TEST_CHANNEL=str(channel))
        result = subprocess.run([self.shell, shell_path(SCRIPT), *args], env=environment,
                                capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')

    def values(self, name):
        directory = self.leds / name
        return tuple((directory / field).read_text().strip() for field in ('brightness', 'trigger'))

    def test_f50_wifi_on_and_off_controls_only_the_verified_wifi_lamp(self):
        untouched = {name: self.values(name) for name in LED_VALUES if name != 'keyboard-backlight'}
        for channel in (6, 36):
            with self.subTest(channel=channel):
                self.run_led('wifi', 'on', channel=channel)
                self.assertEqual(self.values('keyboard-backlight'), ('127', 'none'))
                self.run_led('wifi', 'off', channel=channel)
                self.assertEqual(self.values('keyboard-backlight'), ('0', 'none'))
                self.assertEqual({name: self.values(name) for name in untouched}, untouched)

    def test_f50_cellular_changes_do_not_clear_the_wifi_lamp(self):
        self.run_led('wifi', 'on')
        for state, brightness in (('on', '255'), ('5g', '255'), ('off', '0'), ('error', '0')):
            self.run_led('data', state)
            self.assertEqual(self.values('sc27xx:blue'), (brightness, 'none'))
            self.assertEqual(self.values('keyboard-backlight'), ('127', 'none'))

    def test_u30air_wifi_retains_separate_band_lamps(self):
        untouched = {name: self.values(name) for name in LED_VALUES if name not in ('zte-ldo1', 'zte-ldo2')}
        for channel, expected in ((6, ('1', '0')), (36, ('0', '1'))):
            self.run_led('wifi', 'on', device='u30air', channel=channel)
            self.assertEqual(tuple(self.values(name)[0] for name in ('zte-ldo1', 'zte-ldo2')), expected)
        self.run_led('wifi', 'off', device='u30air')
        self.assertEqual(tuple(self.values(name)[0] for name in ('zte-ldo1', 'zte-ldo2')), ('0', '0'))
        self.assertEqual({name: self.values(name) for name in untouched}, untouched)

    def test_unknown_device_does_not_gain_a_wifi_mapping(self):
        original = {name: self.values(name) for name in LED_VALUES}
        self.run_led('wifi', 'on', device='unknown')
        self.run_led('wifi', 'off', device='unknown')
        self.assertEqual({name: self.values(name) for name in LED_VALUES}, original)


if __name__ == '__main__':
    unittest.main()
