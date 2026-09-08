import unittest
from unittest.mock import AsyncMock, patch
from starlette.requests import Request
from starlette.responses import Response

from receipter import app


class DeploymentTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_browser_cannot_print_after_restart(self):
        request = Request({'type': 'http', 'method': 'POST', 'path': '/api/print',
                           'headers': [(b'x-receipter-build', b'old-build')]})
        send = AsyncMock()
        response = await app.reject_stale_print_controls(request, send)
        self.assertEqual(response.status_code, 409)
        send.assert_not_called()

    async def test_current_browser_and_non_browser_clients_can_print(self):
        for headers in [[], [(b'x-receipter-build', app.BUILD_ID.encode())]]:
            request = Request({'type': 'http', 'method': 'POST', 'path': '/api/print', 'headers': headers})
            send = AsyncMock(return_value=Response('OK'))
            response = await app.reject_stale_print_controls(request, send)
            self.assertEqual(response.status_code, 200)
            send.assert_awaited_once()

    async def test_stop_is_never_blocked_by_stale_browser(self):
        request = Request({'type': 'http', 'method': 'POST', 'path': '/api/interrupt',
                           'headers': [(b'x-receipter-build', b'old-build')]})
        send = AsyncMock(return_value=Response('OK'))
        self.assertEqual((await app.reject_stale_print_controls(request, send)).status_code, 200)
        send.assert_awaited_once()

    async def test_assets_are_frozen_with_backend_and_not_browser_cached(self):
        with patch('pathlib.Path.read_text', side_effect=AssertionError('Live file access')):
            html = app.index()
            script = app.editor_script()
        self.assertIn(app.BUILD_ID.encode(), html.body)
        self.assertNotIn(b'__BUILD_ID__', html.body)
        self.assertEqual(html.headers['cache-control'], 'no-store')
        self.assertEqual(script.headers['cache-control'], 'no-store')
        self.assertIn(b'switchDensity', script.body)
