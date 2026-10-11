"""Strict, bounded local recommendation input. No coercion or network I/O."""
from __future__ import annotations

import copy
import json
import math
import unicodedata

PROFILES = ('model-routing', 'tool-risk', 'intent-domain', 'loop', 'rag-rerank', 'guardrails')
MAX_BYTES = 65536


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def load_request(path: str) -> dict:
    with open(path, 'rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('request too large')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite number')))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('invalid JSON') from exc


def _tree(value, depth=0):
    if depth > 16:
        raise ValueError('request too deep')
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError('JSON keys must be strings')
            _tree(key, depth + 1)
            _tree(item, depth + 1)
    elif type(value) is list:
        for item in value:
            _tree(item, depth + 1)
    elif type(value) is str:
        if any(unicodedata.category(c) in {'Cc', 'Cs'} for c in value):
            raise ValueError('control characters forbidden')
    elif type(value) in (int, float):
        if not math.isfinite(value):
            raise ValueError('nonfinite number')
    elif value is not None and type(value) is not bool:
        raise TypeError('not JSON data')


def _fields(value, keys):
    if type(value) is not dict or set(value) != set(keys.split()):
        raise ValueError('invalid fields')


def _string(value, limit, *, empty=False):
    if type(value) is not str or len(value) > limit or (not empty and not value.strip()):
        raise ValueError('invalid bounded string')


def _bool(value):
    if type(value) is not bool:
        raise TypeError('boolean required')


def _number(value, *, integer=False, minimum=0):
    if type(value) not in ((int,) if integer else (int, float)) or value < minimum:
        raise ValueError('invalid nonnegative number')


def _candidates(value, minimum):
    if type(value) is not list or not minimum <= len(value) <= 16:
        raise ValueError('invalid candidate count')
    ids = []
    for candidate in value:
        if type(candidate) is not dict:
            raise ValueError('candidate must be mapping')
        _string(candidate.get('id'), 128)
        ids.append(candidate['id'])
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate IDs')


def validate_request(profile: str, request: object) -> dict:
    if profile not in PROFILES:
        raise ValueError('unknown profile')
    _tree(request)
    if len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_BYTES:
        raise ValueError('request too large')
    _fields(request, 'schema text environment context')
    if request['schema'] != 'ai-os-recommendation-request/v1':
        raise ValueError('invalid schema')
    _string(request['text'], 8192)
    _string(request['environment'], 128)
    c = request['context']
    if profile == 'model-routing':
        _fields(c, 'candidates local_only budget')
        _bool(c['local_only'])
        _number(c['budget'])
        _candidates(c['candidates'], 0)
        for item in c['candidates']:
            _fields(item, 'id available local capable estimated_cost')
            for key in ('available', 'local', 'capable'):
                _bool(item[key])
            _number(item['estimated_cost'])
    elif profile == 'tool-risk':
        _fields(c, 'tool_id action arguments permitted')
        _string(c['tool_id'], 128)
        if c['action'] not in ('read', 'write', 'delete', 'deploy', 'publish', 'message', 'permission', 'credential'):
            raise ValueError('invalid action')
        if type(c['arguments']) is not dict:
            raise TypeError('arguments must be mapping')
        _bool(c['permitted'])
    elif profile == 'intent-domain':
        _fields(c, 'intents domains')
        for labels in c.values():
            if type(labels) is not dict or not 2 <= len(labels) <= 16 or 'unknown' not in labels:
                raise ValueError('invalid labels')
            for key, description in labels.items():
                _string(key, 128)
                _string(description, 256)
    elif profile == 'loop':
        _fields(c, 'iteration max_iterations elapsed_seconds timeout_seconds cost budget goal_complete verification_pending')
        _number(c['iteration'], integer=True)
        _number(c['max_iterations'], integer=True, minimum=1)
        for key in ('elapsed_seconds', 'timeout_seconds', 'cost', 'budget'):
            _number(c[key])
        _bool(c['goal_complete'])
        _bool(c['verification_pending'])
    elif profile == 'rag-rerank':
        _fields(c, 'query candidates')
        _string(c['query'], 2000)
        _candidates(c['candidates'], 1)
        for item in c['candidates']:
            _fields(item, 'id source excerpt')
            _string(item['source'], 1024)
            _string(item['excerpt'], 512)
    else:
        _fields(c, 'content origin')
        _string(c['content'], 8192)
        _string(c['origin'], 128)
    return copy.deepcopy(request)
