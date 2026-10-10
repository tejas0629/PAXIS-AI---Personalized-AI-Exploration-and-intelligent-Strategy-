import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from .services import generate_learning_response, stream_learning_response
from .views import ChatAPIView, ChatStreamAPIView


class ProviderConfigurationTests(SimpleTestCase):
    def test_groq_settings_are_loaded_from_environment(self):
        self.assertEqual(settings.GROQ_API_KEY, os.getenv('GROQ_API_KEY', ''))
        self.assertEqual(settings.GROQ_MODEL, os.getenv('GROQ_MODEL', ''))


@override_settings(
    GEMINI_API_KEY='gemini-test-key',
    GEMINI_MODEL='gemini-test-model',
    GROQ_API_KEY='groq-test-key',
    GROQ_MODEL='groq-test-model',
    DEBUG=False,
)
class ProviderFallbackTests(SimpleTestCase):
    gemini_payload = '{"response":"Gemini response","roadmap":null}'
    groq_payload = '{"response":"Groq response","roadmap":{"goal":"Python"}}'

    def make_gemini_client(self, response_text=None, error=None):
        client = Mock()
        if error:
            client.models.generate_content.side_effect = error
        else:
            client.models.generate_content.return_value = SimpleNamespace(text=response_text)
        return client

    def make_groq_client(self, response_text=None, error=None):
        client = Mock()
        if error:
            client.chat.completions.create.side_effect = error
        else:
            client.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=response_text))]
            )
        return client

    @patch('chat.services.Groq')
    @patch('chat.services.genai.Client')
    def test_gemini_success_does_not_call_groq(self, gemini_client, groq_client):
        gemini_client.return_value = self.make_gemini_client(self.gemini_payload)

        response = generate_learning_response('Create a roadmap.')

        self.assertEqual(response, ('Gemini response', None))
        gemini_client.assert_called_once()
        groq_client.assert_not_called()

    @patch('chat.services.Groq')
    @patch('chat.services.genai.Client')
    def test_rate_limit_uses_groq_fallback_with_history(self, gemini_client, groq_client):
        error = RuntimeError('rate limited')
        error.status_code = 429
        gemini_client.return_value = self.make_gemini_client(error=error)
        groq_client.return_value = self.make_groq_client(self.groq_payload)
        history = [SimpleNamespace(role='user', message='I want to become a Java developer.')]

        response = generate_learning_response('Current exp 0', history)

        self.assertEqual(response, ('Groq response', {'goal': 'Python'}))
        groq_client.assert_called_once()
        groq_messages = groq_client.return_value.chat.completions.create.call_args.kwargs['messages']
        self.assertEqual(groq_messages[1]['content'], 'I want to become a Java developer.')
        self.assertEqual(groq_messages[-1]['content'], 'Current exp 0')

    @patch('chat.services.Groq')
    @patch('chat.services.genai.Client')
    def test_server_error_uses_groq_fallback(self, gemini_client, groq_client):
        error = RuntimeError('server error')
        error.status_code = 503
        gemini_client.return_value = self.make_gemini_client(error=error)
        groq_client.return_value = self.make_groq_client(self.groq_payload)

        response = generate_learning_response('Create a roadmap.')

        self.assertEqual(response[0], 'Groq response')
        groq_client.assert_called_once()

    @patch('chat.services.Groq')
    @patch('chat.services.genai.Client')
    def test_timeout_uses_groq_fallback(self, gemini_client, groq_client):
        gemini_client.return_value = self.make_gemini_client(error=TimeoutError())
        groq_client.return_value = self.make_groq_client(self.groq_payload)

        response = generate_learning_response('Create a roadmap.')

        self.assertEqual(response[0], 'Groq response')
        groq_client.assert_called_once()

    @patch('chat.services.genai.Client')
    def test_multi_turn_history_is_sent_to_gemini(self, gemini_client):
        gemini_client.return_value = self.make_gemini_client(self.gemini_payload)
        history = [
            SimpleNamespace(role='user', message='I want to become a Java developer.'),
            SimpleNamespace(role='assistant', message='What is your current experience?'),
        ]

        generate_learning_response('Current exp 0', history)

        contents = gemini_client.return_value.models.generate_content.call_args.kwargs['contents']
        self.assertEqual(contents[0]['parts'][0]['text'], 'I want to become a Java developer.')
        self.assertEqual(contents[1]['role'], 'model')
        self.assertEqual(contents[-1]['parts'][0]['text'], 'Current exp 0')

    @patch('chat.services.genai.Client')
    def test_separate_conversation_history_is_not_mixed(self, gemini_client):
        gemini_client.return_value = self.make_gemini_client(self.gemini_payload)
        first_conversation = [SimpleNamespace(role='user', message='Java developer')]
        second_conversation = [SimpleNamespace(role='user', message='Data analyst')]

        generate_learning_response('Current exp 0', first_conversation)
        generate_learning_response('Current exp 0', second_conversation)

        calls = gemini_client.return_value.models.generate_content.call_args_list
        self.assertEqual(calls[0].kwargs['contents'][0]['parts'][0]['text'], 'Java developer')
        self.assertEqual(calls[1].kwargs['contents'][0]['parts'][0]['text'], 'Data analyst')
        self.assertNotIn('Java developer', str(calls[1].kwargs['contents']))

    @patch('chat.services.requests.post')
    @patch('chat.services.genai.Client')
    def test_serper_results_are_evaluated_by_gemini(self, gemini_client, serper_post):
        client = Mock()
        client.models.generate_content.side_effect = [
            SimpleNamespace(text='{"response":"Roadmap ready","roadmap":{"steps":[{"title":"Java syntax","topics":["Keywords"]}]}}'),
            SimpleNamespace(text='{"topics":[{"topic":"Keywords","study_material":{"website":{"name":"Java tutorial","url":"https://example.com/java-syntax","reason":"Covers Java syntax with examples."},"youtube":{"title":"Java Syntax Tutorial","channel":"Learning Channel","url":"https://www.youtube.com/watch?v=abc123","reason":"Explains syntax for beginners."}}}]}'),
        ]
        gemini_client.return_value = client
        serper_post.side_effect = [
            Mock(status_code=200, json=lambda: {'organic': [{'title': 'Java syntax', 'link': 'https://example.com/java-syntax', 'snippet': 'Java syntax tutorial'}]}),
            Mock(status_code=200, json=lambda: {'videos': [{'title': 'Java Syntax Tutorial', 'link': 'https://www.youtube.com/watch?v=abc123', 'channel': 'Learning Channel', 'snippet': 'Java syntax tutorial'}]}),
        ]

        with patch('chat.services.settings.SERPER_API_KEY', 'serper-test-key'):
            response, roadmap = generate_learning_response('Create a Java roadmap.')

        self.assertEqual(response, 'Roadmap ready')
        material = roadmap['steps'][0]['topic_materials'][0]['study_material']
        self.assertEqual(material['website']['url'], 'https://example.com/java-syntax')
        self.assertEqual(material['youtube']['url'], 'https://www.youtube.com/watch?v=abc123')
        selection_prompt = client.models.generate_content.call_args_list[1].kwargs['contents']
        self.assertIn('https://example.com/java-syntax', selection_prompt)
        self.assertIn('https://www.youtube.com/watch?v=abc123', selection_prompt)

    @patch('chat.services.requests.post')
    @patch('chat.services.genai.Client')
    def test_serper_failure_returns_original_roadmap(self, gemini_client, serper_post):
        client = Mock()
        client.models.generate_content.side_effect = [
            SimpleNamespace(text='{"response":"Roadmap ready","roadmap":{"steps":[{"title":"Java syntax"}]}}'),
        ]
        gemini_client.return_value = client
        serper_post.side_effect = RuntimeError('search unavailable')

        with patch('chat.services.settings.SERPER_API_KEY', 'serper-test-key'):
            response, roadmap = generate_learning_response('Create a Java roadmap.')

        self.assertEqual(response, 'Roadmap ready')
        self.assertEqual(roadmap, {'steps': [{'title': 'Java syntax'}]})

    @patch('chat.services.Groq')
    @patch('chat.services.genai.Client')
    def test_groq_failure_returns_safe_api_error(self, gemini_client, groq_client):
        gemini_client.return_value = self.make_gemini_client(error=TimeoutError())
        groq_client.return_value = self.make_groq_client(error=RuntimeError('provider detail must stay hidden'))
        request = APIRequestFactory().post(
            '/api/chat/',
            {
                'message': 'Create a roadmap.',
                'conversation_id': 'client-conversation-id',
                'messages': [{'role': 'user', 'message': 'Previous goal'}],
            },
            format='json',
        )

        response = ChatAPIView.as_view()(request)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.data['error'], 'AI service is temporarily unavailable. Please try again shortly.')
        self.assertNotIn('provider detail', response.data['error'])

    @patch('chat.services.Groq')
    @patch('chat.services.genai.Client')
    def test_non_temporary_gemini_error_does_not_use_groq(self, gemini_client, groq_client):
        gemini_client.return_value = self.make_gemini_client(error=ValueError('invalid request'))

        with self.assertRaises(ValueError):
            generate_learning_response('Create a roadmap.')

        groq_client.assert_not_called()

    @patch('chat.services.genai.Client')
    def test_gemini_text_is_yielded_before_provider_stream_finishes(self, gemini_client):
        consumed = []

        def provider_chunks():
            consumed.append('first')
            yield SimpleNamespace(text='{"response":"First words ')
            consumed.append('remainder')
            yield SimpleNamespace(text='arrive","roadmap":null}')

        client = Mock()
        client.models.generate_content_stream.return_value = provider_chunks()
        gemini_client.return_value = client
        events = stream_learning_response('Explain this topic.')

        self.assertEqual(next(events)['type'], 'progress')
        self.assertEqual(next(events), {'type': 'chunk', 'text': 'First words '})
        self.assertEqual(consumed, ['first'])
        remaining_events = list(events)
        self.assertIn({'type': 'chunk', 'text': 'arrive'}, remaining_events)
        self.assertEqual(remaining_events[-1], {'type': 'done', 'roadmap': None})

    @patch('chat.services.genai.Client')
    def test_completed_roadmap_step_is_emitted_before_remaining_steps(self, gemini_client):
        consumed = []

        def provider_chunks():
            consumed.append('first')
            yield SimpleNamespace(text=(
                '{"response":"Starting the plan.","roadmap":{"goal":"Learn Python",'
                '"steps":[{"title":"Variables","duration":"1 week",'
                '"description":"Learn basic values.","topics":["Variables"]},'
            ))
            consumed.append('remainder')
            yield SimpleNamespace(text=(
                '{"title":"Functions","duration":"1 week",'
                '"description":"Write reusable code.","topics":["Functions"]}],'
                '"duration":"2 weeks","starting_level":"beginner"}}'
            ))

        client = Mock()
        client.models.generate_content_stream.return_value = provider_chunks()
        gemini_client.return_value = client
        events = stream_learning_response('Create a Python roadmap.')

        next(events)
        building_event = next(events)
        partial_roadmap_event = next(events)

        self.assertEqual(building_event['message'], 'Building your learning roadmap...')
        self.assertEqual(partial_roadmap_event['type'], 'roadmap')
        self.assertEqual(partial_roadmap_event['roadmap']['steps'][0]['title'], 'Variables')
        self.assertEqual(consumed, ['first'])

    @patch('chat.services.Groq')
    @patch('chat.services.genai.Client')
    def test_temporary_gemini_failure_uses_groq_stream(self, gemini_client, groq_client):
        error = RuntimeError('temporarily unavailable')
        error.status_code = 503
        gemini = Mock()
        gemini.models.generate_content_stream.side_effect = error
        gemini_client.return_value = gemini
        groq = Mock()
        groq.chat.completions.create.return_value = iter([
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='{"response":"Groq '))]),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='stream","roadmap":null}'))]),
        ])
        groq_client.return_value = groq

        events = list(stream_learning_response('Explain this topic.'))

        self.assertIn({'type': 'chunk', 'text': 'Groq '}, events)
        self.assertIn({'type': 'chunk', 'text': 'stream'}, events)
        self.assertEqual(events[-1], {'type': 'done', 'roadmap': None})
        self.assertTrue(groq.chat.completions.create.call_args.kwargs['stream'])

    @patch('chat.services.requests.post')
    @patch('chat.services.genai.Client')
    def test_roadmap_and_topic_search_progress_are_emitted_as_work_advances(self, gemini_client, serper_post):
        roadmap = {
            'goal': 'Learn Java',
            'steps': [
                {'title': 'Syntax', 'topics': ['Variables']},
                {'title': 'Objects', 'topics': ['Classes']},
            ],
        }
        client = Mock()
        client.models.generate_content_stream.return_value = iter([
            SimpleNamespace(text=json.dumps({'response': 'Roadmap ready.', 'roadmap': roadmap})),
        ])
        client.models.generate_content.return_value = SimpleNamespace(text='{"topics":[]}')
        gemini_client.return_value = client
        serper_post.return_value = Mock(status_code=200, json=lambda: {'organic': []}, raise_for_status=Mock())

        with patch('chat.services.settings.SERPER_API_KEY', 'serper-test-key'):
            events = list(stream_learning_response('Create a Java roadmap.'))

        event_types = [event['type'] for event in events]
        search_events = [event for event in events if event['type'] == 'progress' and event['message'].startswith('Searching')]
        first_roadmap_index = event_types.index('roadmap')
        first_search_index = events.index(search_events[0])
        self.assertEqual(len(search_events), 2)
        self.assertLess(first_roadmap_index, first_search_index)
        self.assertIn('Variables (1/2)', search_events[0]['message'])
        self.assertIn('Classes (2/2)', search_events[1]['message'])
        self.assertEqual(serper_post.call_count, 4)

    @patch('chat.services.genai.Client')
    def test_empty_provider_stream_returns_clear_error(self, gemini_client):
        client = Mock()
        client.models.generate_content_stream.return_value = iter([])
        gemini_client.return_value = client

        events = list(stream_learning_response('Explain this topic.'))

        self.assertEqual(events[-1]['type'], 'error')
        self.assertIn('empty response', events[-1]['message'])

    @patch('chat.services.genai.Client')
    def test_closing_stream_closes_provider_iterator(self, gemini_client):
        class ProviderStream:
            def __init__(self):
                self.closed = False
                self.chunks = iter([
                    SimpleNamespace(text='{"response":"Visible '),
                    SimpleNamespace(text='text","roadmap":null}'),
                ])

            def __iter__(self):
                return self

            def __next__(self):
                return next(self.chunks)

            def close(self):
                self.closed = True

        provider_stream = ProviderStream()
        client = Mock()
        client.models.generate_content_stream.return_value = provider_stream
        gemini_client.return_value = client
        events = stream_learning_response('Explain this topic.')

        next(events)
        next(events)
        events.close()

        self.assertTrue(provider_stream.closed)


@override_settings(
    GEMINI_API_KEY='gemini-test-key',
    GEMINI_MODEL='gemini-test-model',
    DEBUG=False,
)
class StatelessConversationApiTests(SimpleTestCase):
    @patch('chat.views.generate_learning_response')
    def test_client_history_and_conversation_id_are_forwarded(self, generate_response):
        generate_response.return_value = ('Response', None)
        request = APIRequestFactory().post(
            '/api/chat/',
            {
                'message': 'Create a roadmap.',
                'conversation_id': 'client-uuid',
                'messages': [
                    {'role': 'user', 'message': 'I want Java.'},
                    {'role': 'assistant', 'message': 'Java response.'},
                ],
            },
            format='json',
        )

        response = ChatAPIView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['conversation_id'], 'client-uuid')
        self.assertEqual(response.data['response'], 'Response')
        forwarded_history = generate_response.call_args.args[1]
        self.assertEqual(
            forwarded_history,
            [
                {'role': 'user', 'message': 'I want Java.'},
                {'role': 'assistant', 'message': 'Java response.'},
            ],
        )


class StreamingApiTests(SimpleTestCase):
    @patch('chat.views.stream_learning_response')
    def test_stream_endpoint_returns_sse_events(self, stream_response):
        stream_response.return_value = iter([
            {'type': 'progress', 'message': 'Understanding your learning goal...'},
            {'type': 'chunk', 'text': 'Hello'},
            {'type': 'done', 'roadmap': None},
        ])
        request = APIRequestFactory().post(
            '/api/chat/stream/',
            {'message': 'Hello', 'conversation_id': 'stream-conversation'},
            format='json',
        )

        response = ChatStreamAPIView.as_view()(request)
        body = b''.join(response.streaming_content).decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/event-stream')
        self.assertEqual(response['X-Accel-Buffering'], 'no')
        self.assertIn('"text": "Hello"', body)
        self.assertIn('"conversation_id": "stream-conversation"', body)
