"""Ustawienia w folderze „Ustawienia” obok programu (przenoszone przy aktualizacji) i przejęcie starszych plików z profilu."""
import json, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from rccad import settings as st


class SettingsFolderTests(unittest.TestCase):
    def setUp(self):
        self.env = os.environ.pop('RCCAD_CONFIG_DIR', None)
        st._DIR = None
        self.program = Path(tempfile.mkdtemp());self.profile = Path(tempfile.mkdtemp())

    def tearDown(self):
        st._DIR = None
        if self.env is not None:
            os.environ['RCCAD_CONFIG_DIR'] = self.env

    def test_settings_live_next_to_the_exe_and_survive_copying_the_folder(self):
        exe = self.program / 'RCCAD Desktop.exe'
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(exe)), \
             patch.object(st, '_profile_dir', return_value=self.profile):
            self.assertEqual(st.settings_dir(), self.program / 'Ustawienia')
            self.assertTrue(st.write('favorites', {'tools': ['flange', 'extrude']}))
            self.assertTrue((self.program / 'Ustawienia' / 'favorites.json').exists())
            # nowa wersja programu: skopiowany folder Ustawienia daje te same ulubione
            new = Path(tempfile.mkdtemp())
            (new / 'Ustawienia').mkdir()
            (new / 'Ustawienia' / 'favorites.json').write_text((self.program / 'Ustawienia' / 'favorites.json').read_text(encoding='utf-8'), encoding='utf-8')
            st._DIR = None
            with patch.object(sys, 'executable', str(new / 'RCCAD Desktop.exe')):
                self.assertEqual(st.read('favorites'), {'tools': ['flange', 'extrude']})

    def test_older_profile_settings_move_into_the_program_folder(self):
        (self.profile / 'flange.json').write_text(json.dumps({'radius': 1.5}), encoding='utf-8')
        with patch.object(st, 'program_dir', return_value=self.program), patch.object(st, '_profile_dir', return_value=self.profile):
            self.assertEqual(st.read('flange'), {'radius': 1.5})
            self.assertEqual(json.loads((self.program / 'Ustawienia' / 'flange.json').read_text(encoding='utf-8')), {'radius': 1.5})
            self.assertIsNone(st.read('missing'))

    def test_read_only_program_folder_falls_back_to_profile(self):
        with patch.object(st, 'program_dir', return_value=self.program), patch.object(st, '_profile_dir', return_value=self.profile), \
             patch.object(st, '_writable', return_value=False):
            self.assertEqual(st.settings_dir(), self.profile)


if __name__ == '__main__':
    unittest.main()
