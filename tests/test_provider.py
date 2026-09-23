"""Offline contract tests against the installed Hermes, never a live account."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

class ProviderTests(unittest.TestCase):
    def test_catalog_uses_dedicated_key_and_returns_unique_chat_models(self):
        from unittest.mock import patch
        import httpx, json, tempfile
        from vibe_provider import profile, BASE, UA
        seen = []
        payload = {'data': [
            {'id':'chat-b', 'capabilities':{'completion_chat':True}},
            {'id':'embed', 'capabilities':{'completion_chat':False}},
            {'id':'chat-a', 'capabilities':{'completion_chat':True}},
            {'id':'chat-b', 'capabilities':{'completion_chat':True}},
        ]}
        def fake(req):
            seen.append(req)
            return httpx.Response(200, json=payload)
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
                'HERMES_HOME':home, 'MISTRAL_VIBE_API_KEY':'dedicated',
                'MISTRAL_API_KEY':'ordinary'}), patch('httpx.HTTPTransport',
                return_value=httpx.MockTransport(fake)):
            models = profile.fetch_models(api_key='ordinary', base_url=BASE)
        self.assertEqual(models, ['chat-b', 'chat-a'])
        self.assertEqual(len(seen), 1)
        self.assertEqual(str(seen[0].url), BASE + '/models')
        self.assertEqual(seen[0].headers['authorization'], 'Bearer dedicated')
        self.assertEqual(seen[0].headers['user-agent'], UA)

    def test_catalog_fails_closed_on_wrong_origin_redirect_or_malformed_rows(self):
        from unittest.mock import patch
        import httpx, tempfile
        from vibe_provider import profile, BASE
        cases = [
            ('wrong-origin', {'base_url':'https://evil.invalid/v1'}, None),
            ('redirect', {'base_url':BASE}, httpx.Response(302, headers={'location':'https://evil.invalid/models'})),
            ('missing-data', {'base_url':BASE}, httpx.Response(200, json={'models':[]})),
            ('bad-row', {'base_url':BASE}, httpx.Response(200, json={'data':[{'id':'chat-without-capabilities'}]})),
            ('bad-id', {'base_url':BASE}, httpx.Response(200, json={'data':[{'id':7, 'capabilities':{'completion_chat':True}}]})),
        ]
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
                'HERMES_HOME':home, 'MISTRAL_VIBE_API_KEY':'dedicated'}):
            for name, kwargs, response in cases:
                seen = []
                def fake(req, result=response):
                    seen.append(req)
                    return result
                with self.subTest(name=name), patch('httpx.HTTPTransport',
                        return_value=httpx.MockTransport(fake)):
                    self.assertIsNone(profile.fetch_models(api_key='ordinary', **kwargs))
                self.assertEqual(len(seen), 0 if name == 'wrong-origin' else 1)

    def test_profile_is_direct_and_dedicated(self):
        self.assertIsNotNone(importlib.util.find_spec('vibe_provider'), 'provider missing')
        from vibe_provider import profile, UA
        self.assertEqual(profile.name, 'mistral-vibe')
        self.assertEqual(profile.display_name, 'Mistral Vibe')
        self.assertEqual(UA, 'hermes-mistral-vibe/1.0')
        self.assertEqual(profile.auth_type, 'api_key')
        self.assertEqual(profile.env_vars, ('MISTRAL_VIBE_API_KEY',))
        self.assertEqual(profile.fallback_models, ('mistral-vibe-cli-latest',))
        self.assertEqual(profile.api_mode, 'chat_completions')
        self.assertTrue(profile.supports_model_listing)

    def test_dynamic_catalog_model_is_allowed_and_unknown_model_is_rejected(self):
        from unittest.mock import patch
        import httpx, json, tempfile
        from vibe_provider import profile, BASE
        requests = []
        def fake(req):
            requests.append((req.method, str(req.url)))
            if req.method == 'GET':
                return httpx.Response(200, json={'data':[
                    {'id':'chat-visible', 'capabilities':{'completion_chat':True}},
                    {'id':'embed-hidden', 'capabilities':{'completion_chat':False}},
                ]})
            body = json.loads(req.content)
            return httpx.Response(200, json={'id':'fake','object':'chat.completion','created':0,
                'model':body['model'], 'choices':[{'index':0,'message':
                {'role':'assistant','content':'ok'},'finish_reason':'stop'}]})
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
                'HERMES_HOME':home, 'MISTRAL_VIBE_API_KEY':'dedicated'}), patch(
                'httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
            client = profile.create_client(base_url=BASE, api_key='ordinary')
            result = client.chat.completions.create(model='chat-visible', messages=[])
            self.assertEqual(result.choices[0].message.content, 'ok')
            with self.assertRaisesRegex(RuntimeError, 'current dedicated key catalog'):
                client.chat.completions.create(model='embed-hidden', messages=[])
            client.close()
        self.assertEqual([method for method, _ in requests], ['GET', 'POST'])

    def test_catalog_cache_is_scoped_by_home_and_key_without_storing_keys(self):
        from unittest.mock import patch
        import httpx, tempfile
        import vibe_provider as vp
        calls = []
        def fake(req):
            calls.append(req.headers['authorization'])
            suffix = 'one' if req.headers['authorization'] == 'Bearer key-one' else 'two'
            return httpx.Response(200, json={'data':[{
                'id':'chat-' + suffix, 'capabilities':{'completion_chat':True}}]})
        vp._catalog_cache.clear()
        with tempfile.TemporaryDirectory() as home_one, tempfile.TemporaryDirectory() as home_two, patch(
                'httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
            with patch.dict(os.environ, {'HERMES_HOME':home_one,
                    'MISTRAL_VIBE_API_KEY':'key-one'}):
                self.assertEqual(vp.profile.fetch_models(base_url=vp.BASE), ['chat-one'])
                self.assertEqual(vp.profile.fetch_models(base_url=vp.BASE), ['chat-one'])
            with patch.dict(os.environ, {'HERMES_HOME':home_one,
                    'MISTRAL_VIBE_API_KEY':'key-two'}):
                self.assertEqual(vp.profile.fetch_models(base_url=vp.BASE), ['chat-two'])
            with patch.dict(os.environ, {'HERMES_HOME':home_two,
                    'MISTRAL_VIBE_API_KEY':'key-one'}):
                self.assertEqual(vp.profile.fetch_models(base_url=vp.BASE), ['chat-one'])
        self.assertEqual(len(calls), 3)
        cache_text = repr(vp._catalog_cache)
        self.assertNotIn('key-one', cache_text)
        self.assertNotIn('key-two', cache_text)

    def test_client_rebuilds_when_dedicated_key_changes(self):
        from unittest.mock import patch
        import httpx, tempfile
        from vibe_provider import profile, MODEL, BASE
        auth = []
        def fake(req):
            auth.append(req.headers['authorization'])
            return httpx.Response(200, json={'id':'fake','object':'chat.completion','created':0,
                'model':MODEL, 'choices':[{'index':0,'message':
                {'role':'assistant','content':'ok'},'finish_reason':'stop'}]})
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
                'HERMES_HOME':home, 'MISTRAL_VIBE_API_KEY':'key-one'}), patch(
                'httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
            client = profile.create_client(base_url=BASE)
            client.chat.completions.create(model=MODEL, messages=[])
            os.environ['MISTRAL_VIBE_API_KEY'] = 'key-two'
            client.chat.completions.create(model=MODEL, messages=[])
            client.close()
        self.assertEqual(auth, ['Bearer key-one', 'Bearer key-two'])

    def test_missing_dedicated_key_fails_at_request_not_client_hook(self):
        from unittest.mock import patch
        from vibe_provider import profile, MODEL
        from agent.agent_runtime_helpers import _provider_supplied_client
        from providers import register_provider
        from types import SimpleNamespace
        import tempfile
        register_provider(profile)
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
            'HERMES_HOME': home, 'MISTRAL_API_KEY': 'wrong-payg',
            'MISTRAL_VIBE_API_KEY': '',
        }):
            client = _provider_supplied_client(SimpleNamespace(provider=profile.name),
                {'api_key': 'wrong-payg', 'base_url': profile.base_url})
            self.assertIsNotNone(client, 'Hermes must not fall through to ordinary OpenAI client')
            with self.assertRaisesRegex(RuntimeError, 'dedicated'):
                client.chat.completions.create(model=MODEL, messages=[])

    def test_streaming_tool_roundtrip_uses_real_hermes_client_seam(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from vibe_provider import profile, MODEL, BASE, UA
        from providers import register_provider
        from agent.agent_runtime_helpers import _provider_supplied_client
        import httpx, json, tempfile
        requests = []
        def fake_api(request):
            requests.append(json.loads(request.content))
            self.assertEqual(str(request.url), BASE + '/chat/completions')
            self.assertEqual(request.headers['authorization'], 'Bearer fake-plan-key')
            self.assertEqual(request.headers['user-agent'], UA)
            delta = {'tool_calls': [{'index': 0, 'id': 'abc123456', 'type': 'function',
                'function': {'name': 'local_echo', 'arguments': '{"text":"bonjour"}'}}]} if len(requests) == 1 else {'content': 'bonjour'}
            chunk = {'id': 'fake', 'object': 'chat.completion.chunk', 'created': 0,
                'model': MODEL, 'choices': [{'index': 0, 'delta': delta,
                'finish_reason': 'tool_calls' if len(requests) == 1 else 'stop'}]}
            return httpx.Response(200, headers={'content-type':'text/event-stream'},
                content='data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n')
        register_provider(profile)
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME': home,
                'MISTRAL_VIBE_API_KEY': 'fake-plan-key'}), patch('httpx.HTTPTransport', return_value=httpx.MockTransport(fake_api)):
            client = _provider_supplied_client(SimpleNamespace(provider=profile.name),
                {'api_key': 'wrong-payg', 'base_url': BASE})
            messages = [{'role': 'user', 'content': 'echo bonjour'}]
            tools = [{'type': 'function', 'function': {'name': 'local_echo', 'parameters':
                {'type':'object', 'properties': {'text': {'type':'string'}}}}}]
            from agent.chat_completion_helpers import _StreamingCall, _iter_provider_stream_chunks
            wrapper = SimpleNamespace(
                agent=SimpleNamespace(base_url=BASE,
                    _create_request_openai_client=lambda **kw: client,
                    _touch_activity=lambda *a: None),
                clients=SimpleNamespace(set_client=lambda c: c), last_chunk_time={})
            chunks = list(_iter_provider_stream_chunks(_StreamingCall._open_chat_stream(wrapper,
                dict(model=MODEL, messages=messages, tools=tools, stream=True))))
            self.assertEqual(requests[0]['stream_options'], {'include_usage':True})
            call = chunks[0].choices[0].delta.tool_calls[0]
            result = json.loads(call.function.arguments)['text']
            messages += [{'role':'assistant', 'content':None, 'tool_calls': [
                {'id':call.id, 'type':'function', 'function':{'name':call.function.name, 'arguments':call.function.arguments}}]},
                {'role':'tool', 'tool_call_id':call.id, 'content':result}]
            answer = list(client.chat.completions.create(model=MODEL, messages=messages, tools=tools, stream=True))
            self.assertEqual(answer[0].choices[0].delta.content, 'bonjour')
            self.assertEqual(requests[1]['messages'][-1]['role'], 'tool')
            client.close()

    def test_inference_errors_do_not_retry_inside_plugin(self):
        from unittest.mock import patch
        import httpx, tempfile
        from vibe_provider import profile, MODEL
        for status in (401, 403, 429):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as home, patch.dict(os.environ,
                    {'HERMES_HOME':home, 'MISTRAL_VIBE_API_KEY':'fake'}):
                seen = []
                def fake(req):
                    seen.append(req)
                    return httpx.Response(status, json={'error':{'message':'synthetic denial'}})
                with patch('httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
                    client = profile.create_client()
                    with self.assertRaises(Exception) as caught:
                        client.chat.completions.create(model=MODEL, messages=[])
                    self.assertEqual(caught.exception.status_code, status)
                    self.assertEqual(len(seen), 1)
                    client.close()

    def test_unsafe_inference_overrides_rejected_before_io(self):
        from unittest.mock import patch
        import httpx
        from vibe_provider import profile, MODEL, BASE
        cases = [({'base_url':'https://evil.invalid/v1'}, {}),
                 ({}, {'extra_headers':{'Authorization':'Bearer wrong'}}),
                 ({}, {'extra_body':{'model':'payg'}}),
                 ({}, {'extra_query':{'api_key':'wrong'}})]
        with patch.dict(os.environ, {'MISTRAL_VIBE_API_KEY':'fake'}), patch('httpx.HTTPTransport') as transport:
            for client_kw, request_kw in cases:
                with self.subTest(client_kw=client_kw, request_kw=request_kw):
                    client = profile.create_client(**({'base_url':BASE} | client_kw))
                    with self.assertRaisesRegex(RuntimeError, 'restricted'):
                        client.chat.completions.create(**({'model':MODEL, 'messages':[]} | request_kw))
            transport.assert_not_called()

if __name__ == '__main__':
    unittest.main()
