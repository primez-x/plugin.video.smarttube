from pathlib import Path
import re
import unittest
from xml.etree import ElementTree


ROOT = Path(__file__).parents[1]
EXPECTED_SETTINGS = (
    'language', 'region', 'dearrow', 'dislikes',
    'sponsorblock', 'sponsorblock_sponsor', 'sponsorblock_intro_outro',
    'sponsorblock_interaction', 'sponsorblock_filler',
    'sponsorblock_notify')


def localized_ids():
    strings = (ROOT / 'resources' / 'language'
               / 'resource.language.en_gb' / 'strings.po').read_text(
                   encoding='utf-8')
    return set(re.findall(r'msgctxt "#(\d+)"', strings))


class AddonXmlTests(unittest.TestCase):
    def setUp(self):
        self.addon = ElementTree.parse(ROOT / 'addon.xml').getroot()

    def test_identity_and_extensions(self):
        self.assertEqual('plugin.video.smarttube', self.addon.get('id'))
        points = [ext.get('point')
                  for ext in self.addon.findall('extension')]
        self.assertIn('xbmc.python.pluginsource', points)
        self.assertIn('xbmc.service', points)
        imports = [node.get('addon')
                   for node in self.addon.findall('requires/import')]
        self.assertEqual(['xbmc.python', 'inputstream.adaptive'], imports)

    def test_news_names_the_version(self):
        version = self.addon.get('version')
        news = self.addon.findtext('extension/news') or ''
        self.assertTrue(news.strip().splitlines()[0].endswith(version),
                        'first news line must name %s' % version)


class SettingsSchemaTests(unittest.TestCase):
    def setUp(self):
        self.root = ElementTree.parse(
            ROOT / 'resources' / 'settings.xml').getroot()
        self.settings = self.root.findall(
            'section/category/group/setting')

    def test_expected_settings_in_order(self):
        self.assertEqual('1', self.root.get('version'))
        self.assertEqual(list(EXPECTED_SETTINGS),
                         [s.get('id') for s in self.settings])

    def test_every_label_is_localized(self):
        known = localized_ids()
        for setting in self.settings:
            self.assertIn(setting.get('label'), known)
        for category in self.root.findall('section/category'):
            self.assertIn(category.get('label'), known)

    def test_code_string_ids_are_localized(self):
        known = localized_ids()
        for name in ('plugin.py', 'service.py'):
            source = (ROOT / 'resources' / 'lib' / name).read_text(
                encoding='utf-8')
            for string_id in re.findall(
                    r'getLocalizedString\((\d+)\)', source):
                self.assertIn(string_id, known,
                              '%s uses unlocalized #%s' % (name, string_id))
            for string_id in re.findall(r'\((320\d\d),', source):
                self.assertIn(string_id, known)


if __name__ == '__main__':
    unittest.main()
