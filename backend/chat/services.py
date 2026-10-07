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


def _enrich_roadmap_with_study_material(client, roadmap, model):
    if not settings.SERPER_API_KEY:
        return roadmap
    level = roadmap.get('starting_level', 'beginner')
    candidates = []
    for topic in _roadmap_topics(roadmap):
        query = f'{topic} {level} tutorial'
        if settings.DEBUG:
            logger.info('[Serper] Searching for topic: %s', topic)
        try:
            website_results = _serper_search(query, 'search')
            video_results = _serper_search(query, 'videos')
        except Exception as exc:
            if settings.DEBUG:
                logger.warning('[Serper] Search failed (%s): %s', type(exc).__name__, _safe_exception_detail(exc))
            continue
        if settings.DEBUG:
            logger.info('[Serper] Search successful')
        candidates.append({'topic': topic, 'website_results': website_results, 'video_results': video_results})

    if not candidates:
        return roadmap
    prompt = f'{STUDY_MATERIAL_PROMPT}\n{json.dumps(candidates)}'
    result = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type='application/json'),
    )
    response_text = (getattr(result, 'text', '') or '').strip()
    if not response_text:
        return roadmap
    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        return roadmap
    enriched_roadmap = dict(roadmap)
    selected_by_topic = {}
    selected = payload.get('topics') if isinstance(payload, dict) else None
    if not isinstance(selected, list):
        return roadmap
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
