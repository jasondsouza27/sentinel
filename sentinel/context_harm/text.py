r"""Identity masking and versioned, deterministic duplicate ownership keys.

Duplicate word tokens use Python's Unicode ``\b\w+\b`` after masking,
NFC, casefold and whitespace collapse. Each word trigram is a compact UTF-8
canonical JSON array (ensure_ascii=False, sorted keys, no NaN). SimHash uses
occurrence weights, SHA-256's first eight bytes, MSB-first bits and zero ties.
The four buckets are disjoint 16-bit words, most significant word first.
"""
import hashlib
import re
import unicodedata
from collections import Counter

from .contracts import ModelText
from .integrity import canonical_bytes, canonical_sha256

URL_PLACEHOLDER = '[URL]'
USER_PLACEHOLDER = '[USER]'
WORD_PATTERN = r'\b\w+\b'
TOKENIZER_SPEC = {'pattern': WORD_PATTERN, 'flags': ['UNICODE'],
                  'normalization': ['mask_urls_users', 'NFC', 'casefold', 'collapse_whitespace']}
TRIGRAM_SERIALIZATION = {'format': 'canonical_json_array', 'encoding': 'utf-8',
                         'ensure_ascii': False, 'separators': [',', ':'],
                         'sort_keys': True, 'allow_nan': False}
_URL = re.compile(r'\b(?:https?://|ftp://|www\.)[^\s<>"\u201c\u201d]+', re.IGNORECASE)
_USER = re.compile(r'(?<![\w@/])(?:/?u/|@)[\w-]+')
_WORD = re.compile(WORD_PATTERN, re.UNICODE)


def _replace_url(match: re.Match) -> str:
    value = match.group(0)
    suffix = ''
    closing = {')': '(', ']': '[', '}': '{'}
    while value:
        last = value[-1]
        if last in '.,!?;:\'' or (last in closing and value.count(last) > value.count(closing[last])):
            suffix = last + suffix
            value = value[:-1]
        else:
            break
    return URL_PLACEHOLDER + suffix


def mask_text(text: str) -> str:
    """Replace identity spans while preserving words, quotes and punctuation."""
    return _USER.sub(USER_PLACEHOLDER, _URL.sub(_replace_url, text))


def prepare_model_text(value: ModelText) -> ModelText:
    return ModelText(mask_text(value.target), tuple(mask_text(text) for text in value.context))


def normalize_duplicate_text(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFC', mask_text(text)).casefold().split())


def word_tokens(text: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(normalize_duplicate_text(text)))


def simhash_target(text: str) -> int:
    tokens = word_tokens(text)
    trigrams = Counter(zip(tokens, tokens[1:], tokens[2:]))
    sums = [0] * 64
    for trigram, weight in trigrams.items():
        digest = int.from_bytes(hashlib.sha256(canonical_bytes(list(trigram))).digest()[:8], 'big')
        for index in range(64):
            sums[index] += weight if digest & (1 << (63 - index)) else -weight
    fingerprint = 0
    for index, value in enumerate(sums):
        if value > 0:
            fingerprint |= 1 << (63 - index)
    return fingerprint


def duplicate_keys(value: ModelText) -> dict:
    target = normalize_duplicate_text(value.target)
    context = tuple(normalize_duplicate_text(text) for text in value.context)
    meaningful = len(_WORD.findall(target)) >= 8 and len(target) >= 40
    fingerprint = simhash_target(target) if meaningful else None
    return {
        'input_exact': canonical_sha256({'target': target, 'context': context}),
        'target_exact': canonical_sha256(target) if meaningful else None,
        'target_simhash': fingerprint,
        'simhash_buckets': tuple((index, (fingerprint >> (48 - 16 * index)) & 0xffff)
                                  for index in range(4)) if meaningful else (),
        'meaningful_target': meaningful,
    }
