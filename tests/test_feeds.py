"""Failure modes of the signed-out feeds: RSS uploads, charts, categories and related videos."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'resources' / 'lib'))
import innertube  # noqa: E402

CHANNEL = 'UC' + 'a' * 22
OTHER = 'UC' + 'b' * 22


def feed(channel_id, entries):
    body = ''.join(
        '<entry><yt:videoId>{0}</yt:videoId><yt:channelId>{1}</yt:channelId>'
        '<title>{2}</title><link rel="alternate" href="https://www.youtube.com/{3}"/>'
        '<author><name>Author {1}</name></author><published>{4}</published>'
        '<media:group><media:thumbnail url="https://i.ytimg.com/vi/{0}/hqdefault.jpg"/>'
        '<media:community><media:statistics views="12345"/></media:community></media:group>'
        '</entry>'.format(video_id, channel_id, title, link, published)
        for video_id, title, link, published in entries)
    return ('<?xml version="1.0"?><feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
            'xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">'
            '<title>Channel</title>' + body + '</feed>').encode()


class ChannelFeedTests(unittest.TestCase):
    def test_entries_become_video_items_and_shorts_are_dropped(self):
        items = innertube.parse_channel_feed(feed(CHANNEL, [
            ('vid00000001', 'Long &amp; good', 'watch?v=vid00000001', '2026-10-29T15:00:07+00:00'),
            ('short000001', 'A short', 'shorts/short000001', '2026-10-30T15:00:07+00:00')]))
        self.assertEqual(1, len(items))
        item = items[0]
        self.assertEqual(('video', 'vid00000001', 'Long & good', CHANNEL, 'Author ' + CHANNEL),
                         (item['type'], item['id'], item['title'], item['channel_id'], item['author']))
        self.assertEqual(('2026-10-29T15:00:07+00:00', '2026-10-29', '12,345 views'),
                         (item['date'], item['published'], item['views']))
        self.assertTrue(item['thumbnail'].endswith('/vid00000001/hqdefault.jpg'))
        self.assertFalse(item['is_live'])

    def test_malformed_and_empty_feeds(self):
        with self.assertRaises(innertube.InnertubeError):
            innertube.parse_channel_feed(b'<html>Error 404</html')
        self.assertEqual([], innertube.parse_channel_feed(feed(CHANNEL, [])))
        bare = feed(CHANNEL, [('vid00000002', 'Bare', 'watch?v=vid00000002', '')])
        bare = bare.replace(b'<media:community><media:statistics views="12345"/></media:community>', b'')
        self.assertEqual('', innertube.parse_channel_feed(bare)[0]['views'])
        # int() rejects a string of more than 4300 digits and non-ASCII digits
        for views in ('9' * 4301, '\u00b2', '-5'):
            odd = feed(CHANNEL, [('vid00000001', 'Odd', 'watch?v=vid00000001', '')]).replace(
                b'views="12345"', ('views="%s"' % views).encode())
            self.assertEqual('', innertube.parse_channel_feed(odd)[0]['views'], views[:5])

    def test_subscriptions_merge_newest_first_and_report_failures(self):
        feeds = {
            CHANNEL: innertube.parse_channel_feed(feed(CHANNEL, [
                ('old00000001', 'Old', 'watch?v=old00000001', '2026-10-01T00:00:00+00:00'),
                ('new00000001', 'New', 'watch?v=new00000001', '2026-10-29T00:00:00+00:00')])),
            OTHER: innertube.parse_channel_feed(feed(OTHER, [
                ('mid00000001', 'Mid', 'watch?v=mid00000001', '2026-10-15T00:00:00+00:00')])),
        }
        def fetch(channel_id):
            if channel_id == 'UC' + 'c' * 22:
                raise OSError('404')
            return feeds[channel_id]
        items, failures = innertube.subscriptions([CHANNEL, OTHER, 'UC' + 'c' * 22], fetch=fetch)
        self.assertEqual(['new00000001', 'mid00000001', 'old00000001'], [i['id'] for i in items])
        self.assertEqual(['UC' + 'c' * 22], failures)
        self.assertEqual(([], []), innertube.subscriptions([], fetch=fetch))

    def test_feed_request_is_a_plain_get_for_one_channel(self):
        with patch.object(innertube, '_default_get', return_value=feed(CHANNEL, [])) as get:
            innertube.channel_feed(CHANNEL)
        self.assertEqual('https://www.youtube.com/feeds/videos.xml?channel_id=' + CHANNEL, get.call_args.args[0])
        with self.assertRaises(ValueError):
            innertube.channel_feed('../x')


class ChartAndCategoryTests(unittest.TestCase):
    def charts(self, title):
        return {'contents': [{'musicTwoRowItemRenderer': {
            'title': {'runs': [{'text': title}]},
            'navigationEndpoint': {'browseEndpoint': {'browseId': 'VLOLAKtrend'}}}}]}

    def test_trending_chart_is_found_by_title(self):
        self.assertEqual('VLOLAKtrend', innertube.parse_trending_chart(self.charts('Trending 20 Canada')))
        with self.assertRaises(innertube.InnertubeError):
            innertube.parse_trending_chart(self.charts('Top 100 Music Videos'))
        with self.assertRaises(innertube.InnertubeError):
            innertube.parse_trending_chart({})

    def test_trending_reads_charts_with_the_music_client_then_the_playlist(self):
        calls = []
        def transport(url, data, headers, timeout):
            body = json.loads(data)
            calls.append((body['context']['client']['clientName'], body.get('browseId'),
                          body['context']['client']['gl']))
            return json.dumps(self.charts('Trending 20 Canada') if len(calls) == 1 else {}).encode()
        with patch.object(innertube, '_default_opener', side_effect=transport):
            self.assertEqual(([], ''), innertube.trending(hl='de', gl='CA'))
        self.assertEqual([('WEB_REMIX', 'FEmusic_charts', 'CA'), ('WEB', 'VLOLAKtrend', 'CA')], calls)

    def test_chart_titles_are_read_in_english_for_every_language(self):
        languages = []
        def transport(url, data, headers, timeout):
            languages.append(json.loads(data)['context']['client']['hl'])
            return json.dumps(self.charts('Trending 20 Deutschland')).encode()
        with patch.object(innertube, '_default_opener', side_effect=transport):
            self.assertEqual('VLOLAKtrend', innertube.trending_chart(hl='de', gl='DE'))
        self.assertEqual(['en'], languages)

    def test_explore_categories_are_fixed(self):
        self.assertEqual(['fashion', 'gaming', 'learning', 'live', 'music', 'news', 'sports'],
                         sorted(innertube.EXPLORE))
        with self.assertRaises(ValueError):
            innertube.explore('kids')

    def test_gaming_video_cards_are_parsed(self):
        card = {'videoCardRenderer': {
            'videoId': 'game0000001', 'title': {'runs': [{'text': 'Boss fight'}]},
            'bylineText': {'runs': [{'text': 'Gamer', 'navigationEndpoint': {
                'browseEndpoint': {'browseId': CHANNEL}}}]},
            'metadataText': {'simpleText': '14K views · 6 days ago'},
            'lengthText': {'simpleText': '25:00'},
            'thumbnail': {'thumbnails': [{'url': '//i.ytimg.com/x.jpg', 'width': 336}]}}}
        item = innertube.parse_listing_response(card)[0][0]
        self.assertEqual(('game0000001', 'Boss fight', 'Gamer', CHANNEL, 1500, '14K views · 6 days ago'),
                         (item['id'], item['title'], item['author'], item['channel_id'],
                          item['duration'], item['views']))
        self.assertEqual('https://i.ytimg.com/x.jpg', item['thumbnail'])


class ChannelAndRelatedTests(unittest.TestCase):
    def test_channel_metadata_reads_title_and_avatar(self):
        data = {'metadata': {'channelMetadataRenderer': {
            'externalId': CHANNEL, 'title': 'Name',
            'avatar': {'thumbnails': [{'url': 'https://yt3/a=s88', 'width': 88},
                                      {'url': 'https://yt3/a=s900', 'width': 900}]}}}}
        with patch.object(innertube, 'innertube_post', return_value=data):
            self.assertEqual({'id': CHANNEL, 'title': 'Name', 'thumbnail': 'https://yt3/a=s900'},
                             innertube.channel_metadata(CHANNEL))
        with patch.object(innertube, 'innertube_post', return_value={}):
            with self.assertRaises(innertube.InnertubeError):
                innertube.channel_metadata(CHANNEL)

    def test_related_reads_next_and_drops_the_source_video(self):
        data = {'contents': [{'compactVideoRenderer': {'videoId': 'source00001'}},
                             {'compactVideoRenderer': {'videoId': 'related0001'}}]}
        with patch.object(innertube, 'innertube_post', return_value=data) as post:
            items = innertube.related('source00001')
        self.assertEqual(['related0001'], [i['id'] for i in items])
        self.assertEqual(('next', 'web', {'videoId': 'source00001'}), post.call_args.args[:3])


class ChannelLimitTests(unittest.TestCase):
    def test_channel_limit_is_shared_and_enforced(self):
        ids = ['UC' + str(n).zfill(22) for n in range(innertube.MAX_CHANNELS)]
        self.assertEqual(ids, innertube.channel_ids(ids))
        with self.assertRaises(ValueError):
            innertube.channel_ids(ids + ['UC' + 'z' * 22])

    def test_live_lookup_runs_per_channel_and_isolates_failures(self):
        def lookup(channel_id):
            if channel_id == OTHER:
                raise innertube.InnertubeError('offline')
            return {'type': 'video', 'id': 'live' + channel_id[-3:], 'author': 'A', 'is_live': True}
        live, failures = innertube.live_now([CHANNEL, OTHER, 'UC' + 'c' * 22], lookup=lookup)
        self.assertEqual([CHANNEL, 'UC' + 'c' * 22], [v['channel_id'] for v in live])
        self.assertEqual([OTHER], failures)


if __name__ == '__main__':
    unittest.main()
