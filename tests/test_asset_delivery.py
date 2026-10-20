import unittest
from pathlib import Path
from flask import url_for
import test_customer as fixture
from sqlalchemy import event
from asset_delivery import public_asset
panel = fixture.panel

class PublicAssetDeliveryTests(unittest.TestCase):
    setUp = fixture.CustomerFlowTests.setUp
    tearDown = fixture.CustomerFlowTests.tearDown
    admin = fixture.CustomerFlowTests.admin

    def test_versioned_public_asset_can_be_cached_and_revalidated(self):
        version = (Path(__file__).resolve().parents[1] / 'VERSION').read_text().strip()
        with panel.app.test_request_context():
            url = url_for('static', filename='js/lightfall.js')
        self.assertIn('v=' + version, url)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.cache_control.immutable)
        self.assertEqual(response.cache_control.max_age, 31536000)
        follow = self.client.get(url, headers={'If-None-Match': response.headers['ETag']})
        self.assertEqual(follow.status_code, 304)
        self.assertFalse(self.client.get('/static/js/lightfall.js?v=old').cache_control.immutable)

    def test_private_pages_never_get_the_public_asset_policy(self):
        self.admin()
        for url in ['/panel/users', '/panel/settings', '/panel/c/' + self.token + '/dns/999.mobileconfig']:
            response = self.client.get(url)
            self.assertFalse(response.cache_control.immutable)
            self.assertNotEqual(response.cache_control.max_age, 31536000)

    def test_public_file_delivery_does_not_query_admin_sessions(self):
        self.admin()
        calls = []
        def record(*args):
            calls.append(True)
        event.listen(panel.db.engine, 'before_cursor_execute', record)
        try:
            response = self.client.get('/static/js/lightfall.js')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(calls, [])
            self.assertNotIn('Set-Cookie', response.headers)
        finally:
            event.remove(panel.db.engine, 'before_cursor_execute', record)
        for name in ['css/../uploads/a.png', 'brand/a.env', 'css/a\\b.css', 'uploads/a.png']:
            self.assertFalse(public_asset(name))
