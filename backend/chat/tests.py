import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from .services import generate_learning_response
from .views import ChatAPIView


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
