import json
import logging
import re
import socket

import requests
from django.conf import settings
from google import genai
from google.genai import types
from groq import Groq


logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are an AI Personalized Learning Assistant for an AI Learning Path Recommender app.
Understand the user's goal, target skill or career, timeline, current level, and daily study time when available.
Create realistic, practical learning roadmaps broken into logical stages. Prioritize what to learn first, suggest
topics, practical projects, milestones, and the next action. Avoid unrealistic promises and ask one short
clarification question only when critical information is genuinely missing. Respond naturally in English, Hindi,
or Hinglish, matching the user's language. Keep the response concise and useful.

Return only valid JSON in this shape:
{
  "response": "concise natural-language answer",
  "roadmap": {
    "goal": "string",
    "duration": "string",
    "starting_level": "string",
    "steps": [
      {"title": "string", "duration": "string", "description": "string", "topics": ["string"]}
    ],
    "projects": ["string"],
    "milestones": ["string"],
    "next_action": "string"
  }
}
Use null for roadmap when the user has not asked for a learning path or important details are missing.
""".strip()


class GeminiConfigurationError(Exception):
    pass


class GeminiResponseError(Exception):
    pass


class GroqConfigurationError(Exception):
    pass


class GroqResponseError(Exception):
    pass


STUDY_MATERIAL_PROMPT = """
Select one suitable website result and one specific YouTube video result for each roadmap topic from the
provided Serper search results. Evaluate relevance to the exact topic, learner level, clarity, credibility,
and whether the result directly teaches the topic. Use only URLs present in the supplied results. Never invent
URLs, use a homepage when a relevant page exists, or use a YouTube channel homepage. Use null when no suitable
result exists. Keep reasons short.

Return only valid JSON in this shape:
{
    "topics": [
        {
            "topic": "exact topic from the supplied results",
            "study_material": {
                "website": {"name": "string", "url": "https://...", "reason": "short reason"},
                "youtube": {"title": "string", "channel": "string", "url": "https://www.youtube.com/watch?v=...", "reason": "short reason"}
            }
        }
    ]
}

Roadmap:
""".strip()


def _parse_provider_response(response_text, provider):
    response_text = (response_text or '').strip()
    if not response_text:
        raise GeminiResponseError(f'{provider} returned an empty response.')

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise GeminiResponseError(f'{provider} returned an invalid structured response.') from exc

    if not isinstance(payload, dict) or not isinstance(payload.get('response'), str):
        raise GeminiResponseError(f'{provider} returned an incomplete structured response.')

    roadmap = payload.get('roadmap')
    if roadmap is not None and not isinstance(roadmap, dict):
        raise GeminiResponseError(f'{provider} returned an invalid roadmap.')
    return payload['response'].strip(), roadmap


def _valid_resource(resource, resource_type):
    if not isinstance(resource, dict):
        return None
    url = resource.get('url')
    if not isinstance(url, str) or not url.startswith(('http://', 'https://')):
        return None
    required_fields = ('name', 'reason') if resource_type == 'website' else ('title', 'channel', 'reason')
    if any(not isinstance(resource.get(field), str) or not resource[field].strip() for field in required_fields):
        return None
    if resource_type == 'youtube' and 'youtube.com/watch?' not in url and 'youtu.be/' not in url:
        return None
    return {field: resource[field].strip() for field in (*required_fields, 'url')}


def _merge_study_material(roadmap, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('steps'), list):
        return roadmap
    steps = roadmap.get('steps')
    if not isinstance(steps, list):
        return roadmap
    enriched_roadmap = dict(roadmap)
    enriched_steps = []
    for index, step in enumerate(steps):
        enriched_step = dict(step) if isinstance(step, dict) else step
        material = payload['steps'][index].get('study_material') if index < len(payload['steps']) and isinstance(payload['steps'][index], dict) else None
        if isinstance(enriched_step, dict) and isinstance(material, dict):
            website = _valid_resource(material.get('website'), 'website')
            youtube = _valid_resource(material.get('youtube'), 'youtube')
            if website or youtube:
                enriched_step['study_material'] = {'website': website, 'youtube': youtube}
        enriched_steps.append(enriched_step)
    enriched_roadmap['steps'] = enriched_steps
    return enriched_roadmap


def _serper_search(query, search_type):
    if not settings.SERPER_API_KEY:
        return []
    endpoint = 'https://google.serper.dev/videos' if search_type == 'videos' else 'https://google.serper.dev/search'
    response = requests.post(
        endpoint,
        headers={'X-API-KEY': settings.SERPER_API_KEY, 'Content-Type': 'application/json'},
        json={'q': query, 'num': 5},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    results = data.get('videos' if search_type == 'videos' else 'organic', [])
    return [
        {
            key: result.get(key, '')
            for key in (('title', 'link', 'snippet') if search_type != 'videos' else ('title', 'link', 'channel', 'snippet'))
            if result.get(key)
        }
        for result in results
        if result.get('link')
    ]


def _roadmap_topics(roadmap):
    topics = []
    for step in roadmap.get('steps', []) if isinstance(roadmap.get('steps'), list) else []:
        if not isinstance(step, dict):
            continue
        step_topics = step.get('topics') or [step.get('title')]
        topics.extend(topic for topic in step_topics if isinstance(topic, str) and topic.strip())
    return topics


def _enrich_roadmap_events(client, roadmap, model):
    if not settings.SERPER_API_KEY:
        yield 'roadmap', roadmap
        return
    level = roadmap.get('starting_level', 'beginner')
    candidates = []
    topics = _roadmap_topics(roadmap)
    for index, topic in enumerate(topics, start=1):
        query = f'{topic} {level} tutorial'
        if settings.DEBUG:
            logger.info('[Serper] Searching for topic: %s', topic)
        try:
            yield 'search', {
                'index': index,
                'total': len(topics),
                'topic': topic,
                'search_type': 'web',
            }
            website_results = _serper_search(query, 'search')
            yield 'search', {
                'index': index,
                'total': len(topics),
                'topic': topic,
                'search_type': 'videos',
            }
            video_results = _serper_search(query, 'videos')
        except Exception as exc:
            if settings.DEBUG:
                logger.warning('[Serper] Search failed (%s): %s', type(exc).__name__, _safe_exception_detail(exc))
            continue
        if settings.DEBUG:
            logger.info('[Serper] Search successful')
        candidates.append({'topic': topic, 'website_results': website_results, 'video_results': video_results})

    if not candidates:
        yield 'roadmap', roadmap
        return
    prompt = f'{STUDY_MATERIAL_PROMPT}\n{json.dumps(candidates)}'
    result = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type='application/json'),
    )
    response_text = (getattr(result, 'text', '') or '').strip()
    if not response_text:
        yield 'roadmap', roadmap
        return
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        yield 'roadmap', roadmap
        return
    enriched_roadmap = dict(roadmap)
    selected_by_topic = {}
    selected = payload.get('topics') if isinstance(payload, dict) else None
    if not isinstance(selected, list):
        yield 'roadmap', roadmap
        return
    for item in selected:
        if not isinstance(item, dict) or not isinstance(item.get('topic'), str):
            continue
        material = item.get('study_material')
        if not isinstance(material, dict):
            continue
        website = _valid_resource(material.get('website'), 'website')
        youtube = _valid_resource(material.get('youtube'), 'youtube')
        if website or youtube:
            selected_by_topic[item['topic'].strip().lower()] = {'website': website, 'youtube': youtube}
    enriched_steps = []
    for step in roadmap.get('steps', []):
        if not isinstance(step, dict):
            enriched_steps.append(step)
            continue
        enriched_step = dict(step)
        topic_materials = []
        topics = step.get('topics') if isinstance(step.get('topics'), list) else [step.get('title')]
        for topic in topics:
            if isinstance(topic, str) and topic.strip():
                material = selected_by_topic.get(topic.strip().lower())
                if material:
                    topic_materials.append({'topic': topic, 'study_material': material})
        if topic_materials:
            enriched_step['topic_materials'] = topic_materials
        enriched_steps.append(enriched_step)
    enriched_roadmap['steps'] = enriched_steps
    yield 'roadmap', enriched_roadmap


def _enrich_roadmap_with_study_material(client, roadmap, model):
    enriched_roadmap = roadmap
    for event_type, event_data in _enrich_roadmap_events(client, roadmap, model):
        if event_type == 'roadmap':
            enriched_roadmap = event_data
    return enriched_roadmap


def _safe_exception_detail(exc):
    detail = str(exc)
    for secret in (
        getattr(settings, 'GEMINI_API_KEY', ''),
        getattr(settings, 'GROQ_API_KEY', ''),
    ):
        if secret:
            detail = detail.replace(secret, '[REDACTED]')
    return re.sub(r'(AIza[0-9A-Za-z_-]+|gsk_[0-9A-Za-z_-]+)', '[REDACTED]', detail)


def _is_temporary_gemini_error(exc):
    status_code = getattr(exc, 'status_code', None) or getattr(exc, 'code', None)
    if hasattr(status_code, 'value'):
        status_code = status_code.value
    if isinstance(status_code, int) and (status_code == 429 or 500 <= status_code <= 599):
        return True

    error_name = type(exc).__name__.lower()
    temporary_names = (
        'ratelimit',
        'resourceexhausted',
        'toomanyrequests',
        'serviceunavailable',
        'internalserver',
        'deadlineexceeded',
        'timeout',
        'connection',
    )
    return isinstance(exc, (ConnectionError, TimeoutError, socket.timeout)) or any(
        name in error_name for name in temporary_names
    )


class _JsonStringFieldStream:
    def __init__(self, field_name):
        self.field_pattern = re.compile(rf'"{re.escape(field_name)}"\s*:\s*"')
        self.buffer = ''
        self.position = 0
        self.started = False
        self.finished = False

    def feed(self, fragment):
        self.buffer += fragment
        if self.finished:
            return ''
        if not self.started:
            match = self.field_pattern.search(self.buffer)
            if not match:
                return ''
            self.position = match.end()
            self.started = True

        decoded = []
        while self.position < len(self.buffer):
            character = self.buffer[self.position]
            if character == '"':
                self.finished = True
                self.position += 1
                break
            if character == '\\':
                if self.position + 1 >= len(self.buffer):
                    break
                escape_end = self.position + 2
                if self.buffer[self.position + 1] == 'u':
                    escape_end = self.position + 6
                    if escape_end > len(self.buffer):
                        break
                escaped = self.buffer[self.position:escape_end]
                try:
                    decoded.append(json.loads(f'"{escaped}"'))
                except json.JSONDecodeError:
                    break
                self.position = escape_end
                continue
            decoded.append(character)
            self.position += 1
        return ''.join(decoded)


def _partial_roadmap(raw_response):
    roadmap_match = re.search(r'"roadmap"\s*:\s*\{', raw_response)
    if not roadmap_match:
        return None

    decoder = json.JSONDecoder()
    object_start = roadmap_match.end() - 1
    roadmap_prefix = raw_response[object_start:]
    goal_match = re.search(r'(?<!\\)"goal"\s*:\s*', roadmap_prefix)
    steps_match = re.search(r'(?<!\\)"steps"\s*:\s*\[', roadmap_prefix)
    if not goal_match or not steps_match:
        return None

    goal_start = object_start + goal_match.end()
    try:
        goal, _ = decoder.raw_decode(raw_response, goal_start)
    except json.JSONDecodeError:
        return None
    if not isinstance(goal, str) or not goal.strip():
        return None

    steps_start = object_start + steps_match.end()
    position = steps_start
    steps = []
    while position < len(raw_response):
        while position < len(raw_response) and (raw_response[position].isspace() or raw_response[position] == ','):
            position += 1
        if position >= len(raw_response) or raw_response[position] == ']':
            break
        try:
            step, end = decoder.raw_decode(raw_response, position)
        except json.JSONDecodeError:
            break
        if not isinstance(step, dict) or not isinstance(step.get('title'), str) or not step['title'].strip():
            break
        steps.append(step)
        position = end

    if not steps:
        return None
    partial = {'goal': goal, 'steps': steps}
    for field in ('duration', 'starting_level'):
        field_match = re.search(rf'(?<!\\)"{field}"\s*:\s*', roadmap_prefix)
        if field_match:
            value_start = object_start + field_match.end()
            try:
                value, _ = decoder.raw_decode(raw_response, value_start)
            except json.JSONDecodeError:
                continue
            if isinstance(value, str):
                partial[field] = value
    return partial


def _stream_response_chunks(iterator, provider):
    field_stream = _JsonStringFieldStream('response')
    raw_response = []
    try:
        for chunk in iterator:
            if provider == 'Gemini':
                fragment = getattr(chunk, 'text', '') or ''
            else:
                choices = getattr(chunk, 'choices', [])
                delta = getattr(choices[0], 'delta', None) if choices else None
                fragment = getattr(delta, 'content', '') or ''
            raw_response.append(fragment)
            visible_text = field_stream.feed(fragment)
            yield fragment, visible_text
    finally:
        close = getattr(iterator, 'close', None)
        if close:
            try:
                close()
            except Exception:
                logger.debug('[AI] Provider stream cleanup failed.')
    return ''.join(raw_response)


def stream_learning_response(message, conversation_history=None):
    yield {'type': 'progress', 'message': 'Understanding your learning goal...'}
    provider = 'Gemini'
    client = None
    iterator = None
    raw_parts = []
    response_parts = []
    build_status_sent = False
    partial_step_count = 0

    try:
        if not settings.GEMINI_API_KEY:
            raise GeminiConfigurationError('Gemini API key is not configured. Set GEMINI_API_KEY in .env.')
        if not settings.GEMINI_MODEL:
            raise GeminiConfigurationError('Gemini model is not configured. Set GEMINI_MODEL in .env.')
        client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=120_000),
        )
        iterator = client.models.generate_content_stream(
            model=settings.GEMINI_MODEL,
            contents=_provider_history(message, conversation_history),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type='application/json',
            ),
        )
        for fragment, visible_text in _stream_response_chunks(iterator, 'Gemini'):
            raw_parts.append(fragment)
            accumulated_raw = ''.join(raw_parts)
            if not build_status_sent and re.search(r'"roadmap"\s*:\s*\{', accumulated_raw):
                yield {'type': 'progress', 'message': 'Building your learning roadmap...'}
                build_status_sent = True
            partial_roadmap = _partial_roadmap(accumulated_raw)
            if partial_roadmap and len(partial_roadmap['steps']) > partial_step_count:
                partial_step_count = len(partial_roadmap['steps'])
                yield {'type': 'roadmap', 'roadmap': partial_roadmap}
            if visible_text:
                response_parts.append(visible_text)
                yield {'type': 'chunk', 'text': visible_text}
    except Exception as gemini_error:
        if iterator and hasattr(iterator, 'close'):
            iterator.close()
        if not _is_temporary_gemini_error(gemini_error) or response_parts:
            yield {'type': 'error', 'message': 'The AI service could not complete this response. Please try again.'}
            return
        provider = 'Groq'
        raw_parts = []
        response_parts = []
        partial_step_count = 0
        yield {'type': 'progress', 'message': 'Gemini is unavailable; trying the fallback provider...'}
        try:
            if not settings.GROQ_API_KEY or not settings.GROQ_MODEL:
                raise GroqConfigurationError('Groq is not configured.')
            client = Groq(api_key=settings.GROQ_API_KEY)
            iterator = client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=_groq_messages(message, conversation_history),
                response_format={'type': 'json_object'},
                stream=True,
                timeout=120.0,
            )
            for fragment, visible_text in _stream_response_chunks(iterator, 'Groq'):
                raw_parts.append(fragment)
                accumulated_raw = ''.join(raw_parts)
                if not build_status_sent and re.search(r'"roadmap"\s*:\s*\{', accumulated_raw):
                    yield {'type': 'progress', 'message': 'Building your learning roadmap...'}
                    build_status_sent = True
                partial_roadmap = _partial_roadmap(accumulated_raw)
                if partial_roadmap and len(partial_roadmap['steps']) > partial_step_count:
                    partial_step_count = len(partial_roadmap['steps'])
                    yield {'type': 'roadmap', 'roadmap': partial_roadmap}
                if visible_text:
                    response_parts.append(visible_text)
                    yield {'type': 'chunk', 'text': visible_text}
        except Exception:
            if iterator and hasattr(iterator, 'close'):
                iterator.close()
            yield {'type': 'error', 'message': 'Both AI providers are temporarily unavailable. Please try again shortly.'}
            return

    try:
        ai_response, roadmap = _parse_provider_response(''.join(raw_parts), provider)
        emitted_response = ''.join(response_parts)
        if ai_response.startswith(emitted_response) and ai_response != emitted_response:
            remainder = ai_response[len(emitted_response):]
            yield {'type': 'chunk', 'text': remainder}
        elif ai_response != emitted_response:
            raise GeminiResponseError(f'{provider} returned an invalid streamed response.')
    except GeminiResponseError as exc:
        yield {'type': 'error', 'message': str(exc)}
        return

    if roadmap:
        yield {'type': 'roadmap', 'roadmap': roadmap}
        if provider == 'Gemini' and settings.SERPER_API_KEY and _roadmap_topics(roadmap):
            try:
                for event_type, event_data in _enrich_roadmap_events(client, roadmap, settings.GEMINI_MODEL):
                    if event_type == 'search':
                        yield {
                            'type': 'progress',
                            'message': (
                                f"Finding relevant videos for {event_data['topic']} "
                                f"({event_data['index']}/{event_data['total']})..."
                                if event_data['search_type'] == 'videos'
                                else f"Searching for relevant resources: {event_data['topic']} "
                                f"({event_data['index']}/{event_data['total']})..."
                            ),
                            'topic': event_data['topic'],
                            'search_kind': event_data['search_type'],
                            'index': event_data['index'],
                            'total': event_data['total'],
                        }
                    elif event_type == 'roadmap':
                        roadmap = event_data
                        yield {'type': 'roadmap', 'roadmap': roadmap}
            except Exception as exc:
                logger.warning(
                    '[Gemini] Study material search unavailable; returning roadmap without materials (%s).',
                    type(exc).__name__,
                )
    yield {'type': 'done', 'roadmap': roadmap}


def _message_field(item, field_name):
    if isinstance(item, dict):
        return item.get(field_name)
    return getattr(item, field_name, None)


def _provider_history(message, conversation_history):
    if not conversation_history:
        return message
    return [
        {
            'role': 'user' if _message_field(item, 'role') == 'user' else 'model',
            'parts': [{'text': _message_field(item, 'message')}],
        }
        for item in conversation_history
    ] + [{'role': 'user', 'parts': [{'text': message}]}]


def _groq_messages(message, conversation_history):
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    messages.extend(
        {
            'role': _message_field(item, 'role'),
            'content': _message_field(item, 'message'),
        }
        for item in conversation_history or []
    )
    messages.append({'role': 'user', 'content': message})
    return messages


def _generate_groq_response(message, conversation_history=None):
    if not settings.GROQ_API_KEY:
        raise GroqConfigurationError('Groq API key is not configured. Set GROQ_API_KEY in .env.')
    if not settings.GROQ_MODEL:
        raise GroqConfigurationError('Groq model is not configured. Set GROQ_MODEL in .env.')

    try:
        client = Groq(api_key=settings.GROQ_API_KEY)
        result = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=_groq_messages(message, conversation_history),
            response_format={'type': 'json_object'},
        )
    except Exception as exc:
        logger.error('[Groq] Fallback provider failed.')
        raise GroqResponseError('The fallback AI service is temporarily unavailable.') from exc

    try:
        response_text = result.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise GroqResponseError('Groq returned an incomplete structured response.') from exc

    try:
        return _parse_provider_response(response_text, 'Groq')
    except GeminiResponseError as exc:
        raise GroqResponseError(str(exc)) from exc


def generate_learning_response(message, conversation_history=None):
    if not settings.GEMINI_API_KEY:
        raise GeminiConfigurationError('Gemini API key is not configured. Set GEMINI_API_KEY in .env.')
    if not settings.GEMINI_MODEL:
        raise GeminiConfigurationError('Gemini model is not configured. Set GEMINI_MODEL in .env.')

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        if settings.DEBUG:
            logger.info('[Gemini] Calling model: %s', settings.GEMINI_MODEL)
        result = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=_provider_history(message, conversation_history),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type='application/json',
            ),
        )
        if settings.DEBUG:
            logger.info('[Gemini] Response received successfully')
    except Exception as exc:
        if settings.DEBUG:
            logger.error('[Gemini] API call failed: Gemini request could not be completed.')
        if _is_temporary_gemini_error(exc):
            logger.warning('[Gemini] Primary provider unavailable. Switching to Groq fallback.')
            return _generate_groq_response(message, conversation_history)
        raise

    response, roadmap = _parse_provider_response(getattr(result, 'text', ''), 'Gemini')
    if roadmap:
        try:
            roadmap = _enrich_roadmap_with_study_material(client, roadmap, settings.GEMINI_MODEL)
        except Exception as exc:
            if settings.DEBUG:
                logger.warning(
                    '[Gemini] Study material search failed (%s): %s; returning roadmap without materials.',
                    type(exc).__name__,
                    _safe_exception_detail(exc),
                )
            else:
                logger.warning('[Gemini] Study material search unavailable; returning roadmap without materials.')
    return response, roadmap
