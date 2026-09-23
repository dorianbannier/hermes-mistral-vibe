import os, sys, unittest, tempfile, json, hashlib, base64
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import vibe_provider as vp

class AuthTests(unittest.TestCase):
    def test_mocked_login_rejects_unsafe_urls_without_opening_browser(self):
        for field, value in [('sign_in_url','https://evil.invalid/login'),
                             ('poll_url','https://console.mistral.ai@evil.invalid/poll'),
                             ('sign_in_url','http://console.mistral.ai/login'),
                             ('poll_url','https://console.mistral.ai:444/poll'),
                             ('process_id','../escape')]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME':home}):
                process = {'process_id':'test', 'sign_in_url':vp.CONSOLE+'/login',
                           'poll_url':vp.CONSOLE+'/poll', 'expires_at':'2099-01-01T00:00:00Z'}
                process[field] = value
                opened, calls = [], []
                def fake(req):
                    calls.append(req)
                    return httpx.Response(200, json=process)
                with patch('httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
                    with self.assertRaisesRegex(RuntimeError, 'Unsafe'):
                        vp.login(open_browser=opened.append)
                self.assertEqual(opened, [])
                self.assertEqual(len(calls), 1)
                self.assertFalse(Path(home, 'auth.json').exists())


    def test_mocked_poll_pending_then_denied_is_bounded_and_redacted(self):
        polls = []
        def fake(req):
            self.assertEqual(req.extensions['timeout']['read'], 15)
            if req.method == 'POST':
                return httpx.Response(200, json={'process_id':'test', 'sign_in_url':vp.CONSOLE+'/login',
                    'poll_url':vp.CONSOLE+'/poll', 'expires_at':'2099-01-01T00:00:00Z'})
            polls.append(req)
            return httpx.Response(200, json={'status':'pending' if len(polls)==1 else 'denied', 'message':'SECRET'})
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME':home}), patch('httpx.HTTPTransport', return_value=httpx.MockTransport(fake)), patch('time.sleep'):
            with self.assertRaisesRegex(RuntimeError, '^Browser sign-in denied$'):
                vp.login(open_browser=lambda url: None)
            self.assertEqual(len(polls), 2)
            self.assertFalse(Path(home, 'auth.json').exists())


    def test_mocked_expiry_cancel_and_http_errors_never_store_credentials(self):
        for scenario in ('expired', 'cancel', 'redirect', 'timeout', 'bad_json', '401', '429'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME':home}):
                calls = []
                def fake(req):
                    calls.append(req)
                    if scenario == 'timeout':
                        raise httpx.ReadTimeout('SECRET', request=req)
                    if scenario in ('401', '429', 'redirect'):
                        return httpx.Response(302 if scenario=='redirect' else int(scenario), headers={'location':'https://evil.invalid'}, text='SECRET')
                    if scenario == 'bad_json':
                        return httpx.Response(200, text='SECRET')
                    return httpx.Response(200, json={'process_id':'test', 'sign_in_url':vp.CONSOLE+'/login',
                        'poll_url':vp.CONSOLE+'/poll', 'expires_at':'2000-01-01T00:00:00Z' if scenario=='expired' else '2099-01-01T00:00:00Z'})
                def browser(url):
                    if scenario == 'cancel':
                        raise KeyboardInterrupt()
                with patch('httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
                    with self.assertRaises(RuntimeError) as caught:
                        vp.login(open_browser=browser)
                self.assertNotIn('SECRET', str(caught.exception))
                self.assertEqual(len(calls), 1)
                self.assertFalse(Path(home, 'auth.json').exists())

    def test_auth_handler_lifecycle_with_real_pool_and_mocked_login(self):
        from types import SimpleNamespace
        import io, contextlib
        from agent.credential_pool import PooledCredential, load_pool
        self.assertTrue(callable(vp.profile.auth_handler), 'auth handler missing')
        args = SimpleNamespace(no_browser=True)
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME':home, 'MISTRAL_VIBE_API_KEY':''}), contextlib.redirect_stdout(io.StringIO()) as out:
            pool = load_pool(vp.SLUG)
            pool.add_entry(PooledCredential(provider=vp.SLUG, id='test', label='test', auth_type='api_key',
                priority=0, source='manual', access_token='fake-pool-key', base_url=vp.BASE))
            self.assertTrue(vp.profile.auth_handler('status', args))
            self.assertIn('configured', out.getvalue())
            with patch('httpx.HTTPTransport', return_value=httpx.MockTransport(lambda r: httpx.Response(403, json={'error':'denied'}))):
                client = vp.profile.create_client(base_url=vp.BASE, api_key='wrong-key')
                with self.assertRaises(Exception) as caught:
                    client.chat.completions.create(model=vp.MODEL, messages=[])
                self.assertEqual(getattr(caught.exception, 'status_code', None), 403)
                client.close()
            self.assertTrue(vp.profile.auth_handler('logout', args))
            self.assertEqual(vp.dedicated_key(), '')
            with patch.object(vp, 'login', return_value={'plan_type':'test'}) as login:
                self.assertTrue(vp.profile.auth_handler('add', args))
                login.assert_called_once()
            with self.assertRaisesRegex(RuntimeError, 'refresh'):
                vp.profile.auth_handler('refresh', args)
            self.assertNotIn('fake-pool-key', out.getvalue())

    def test_mocked_browser_pkce_exchange_persists_only_dedicated_pool(self):
        self.assertTrue(callable(getattr(vp, 'login', None)), 'browser login missing')
        calls = []
        def fake_console(req):
            calls.append(req)
            path = req.url.path
            if path == '/api/vibe/sign-in':
                return httpx.Response(200, json={'process_id':'test-process',
                    'sign_in_url':'https://console.mistral.ai/vibe/sign-in/test-process',
                    'poll_url':'https://console.mistral.ai/api/vibe/sign-in/test-process',
                    'expires_at':'2099-01-01T00:00:00Z'})
            if path.endswith('/exchange'):
                data = json.loads(req.content)
                first = json.loads(calls[0].content)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(data['code_verifier'].encode()).digest()).decode().rstrip('=')
                self.assertEqual(first, {'code_challenge':challenge, 'code_challenge_method':'S256'})
                self.assertEqual(data['exchange_token'], 'fake-exchange')
                return httpx.Response(200, json={'api_key':'fake-plan-key'})
            if path.endswith('/whoami'):
                self.assertEqual(req.headers['authorization'], 'Bearer fake-plan-key')
                return httpx.Response(200, json={'plan_type':'pro', 'plan_name':'Test only'})
            return httpx.Response(200, json={'status':'completed', 'exchange_token':'fake-exchange'})
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME':home,
            'MISTRAL_VIBE_API_KEY':'', 'MISTRAL_API_KEY':'fake-payg'}), patch('httpx.HTTPTransport', return_value=httpx.MockTransport(fake_console)):
            opened = []
            vp.login(open_browser=opened.append)
            self.assertEqual(len(opened), 1)
            from hermes_cli.auth import read_credential_pool
            rows = read_credential_pool('mistral-vibe')
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['access_token'], 'fake-plan-key')
            self.assertEqual(rows[0]['auth_type'], 'api_key')
            self.assertFalse(read_credential_pool('mistral'))
            self.assertEqual(Path(home, 'auth.json').stat().st_mode & 0o777, 0o600)
            self.assertEqual(vp.dedicated_key(), 'fake-plan-key')
