"""Shared text masking and independent deterministic duplicate vectors."""
import importlib
import unittest

from sentinel.context_harm.contracts import ModelText


class HarmTextTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module('sentinel.context_harm.text')
        except ModuleNotFoundError:
            self.fail('Task 2 text interfaces are not implemented')

    def test_masking_removes_username_and_url_spelling_in_both_branches(self):
        a = ModelText('@Alice u/Bob /u/Carol: visit https://one.example/path.', ('@Earlier www.one.example!',))
        b = ModelText('@Writer u/Other /u/Different: visit https://two.example/else.', ('@Before www.two.example!',))
        prepared = self.api.prepare_model_text(a)
        self.assertEqual(prepared, self.api.prepare_model_text(b))
        self.assertEqual(prepared.target, '[USER] [USER] [USER]: visit [URL].')
        self.assertEqual(prepared.context, ('[USER] [URL]!',))

    def test_masking_preserves_quotes_and_surrounding_punctuation(self):
        value = ModelText('She wrote "@writer, see https://one.example/a" (https://one.example/b).')
        self.assertEqual(self.api.prepare_model_text(value).target,
                         'She wrote "[USER], see [URL]" ([URL]).')

    def test_masking_is_idempotent_and_does_not_change_ordinary_words(self):
        value = ModelText('A menu/name is not a username. Email a@example.org.', ('Look at [USER] and [URL].',))
        prepared = self.api.prepare_model_text(value)
        self.assertEqual(prepared, value)
        self.assertEqual(self.api.prepare_model_text(prepared), prepared)

    def test_duplicate_normalization_masks_then_nfc_casefolds_whitespace(self):
        a = ModelText('CAFÉ STRASSE  @Alice https://one.example', ('Earlier\nWords',))
        b = ModelText('cafe\u0301 straße @Bob https://two.example', ('earlier words',))
        self.assertEqual(self.api.duplicate_keys(a)['input_exact'], self.api.duplicate_keys(b)['input_exact'])

    def test_exact_complete_input_key_preserves_context_order_and_turn_boundaries(self):
        values = (ModelText('target', ('a', 'b')), ModelText('target', ('b', 'a')),
                  ModelText('target', ('a b',)), ModelText('target a', ('b',)))
        self.assertEqual(len({self.api.duplicate_keys(value)['input_exact'] for value in values}), 4)

    def test_short_generic_target_is_compared_only_with_complete_input(self):
        first = self.api.duplicate_keys(ModelText('yes', ('one context',)))
        second = self.api.duplicate_keys(ModelText('yes', ('other context',)))
        self.assertFalse(first['meaningful_target'])
        self.assertIsNone(first['target_exact'])
        self.assertIsNone(first['target_simhash'])
        self.assertEqual(first['simhash_buckets'], ())
        self.assertNotEqual(first['input_exact'], second['input_exact'])

    def test_meaningful_target_requires_both_eight_tokens_and_forty_normalized_chars(self):
        below = self.api.duplicate_keys(ModelText('one two three four five six seven eight'))
        boundary = self.api.duplicate_keys(ModelText('one two three four five six seven eight!'))
        fewer_words = self.api.duplicate_keys(ModelText('longword longword longword longword longword longword longword'))
        self.assertFalse(below['meaningful_target'])
        self.assertTrue(boundary['meaningful_target'])
        self.assertFalse(fewer_words['meaningful_target'])

    def test_unicode_word_tokens_count_as_meaningful_words(self):
        value = ModelText('élan naïve café façade über piñata résumé jalapeño')
        self.assertTrue(self.api.duplicate_keys(value)['meaningful_target'])

    def test_meaningful_target_exact_key_is_independent_of_context(self):
        target = 'eight distinct ordinary words make this sentence meaningful enough'
        a = self.api.duplicate_keys(ModelText(target, ('one',)))
        b = self.api.duplicate_keys(ModelText(target, ('another',)))
        self.assertEqual(a['target_exact'], b['target_exact'])
        self.assertEqual(a['target_simhash'], b['target_simhash'])
        self.assertNotEqual(a['input_exact'], b['input_exact'])

    def test_single_trigram_simhash_matches_sha256_first_eight_bytes_big_endian(self):
        self.assertEqual(self.api.simhash_target('alpha beta gamma'), 11808866096198036315)

    def test_two_trigram_ties_map_to_zero(self):
        self.assertEqual(self.api.simhash_target('alpha beta gamma delta'), 9457704507632328721)

    def test_simhash_has_no_word_trigrams_for_fewer_than_three_tokens(self):
        for value in ('', 'alpha', 'alpha beta'):
            with self.subTest(value=value):
                self.assertEqual(self.api.simhash_target(value), 0)

    def test_simhash_normalizes_case_unicode_and_masked_identifiers(self):
        a = 'CAFÉ @Alice visits https://one.example today'
        b = 'cafe\u0301 @Bob visits https://two.example today'
        self.assertEqual(self.api.simhash_target(a), self.api.simhash_target(b))

    def test_four_disjoint_buckets_use_most_significant_word_first(self):
        value = self.api.duplicate_keys(ModelText('one two three four five six seven eight!'))
        fingerprint = value['target_simhash']
        buckets = value['simhash_buckets']
        self.assertEqual(tuple(index for index, _ in buckets), (0, 1, 2, 3))
        self.assertTrue(all(0 <= bucket < 65536 for _, bucket in buckets))
        restored = sum(bucket << (48 - 16 * index) for index, bucket in buckets)
        self.assertEqual(restored, fingerprint)

    def test_occurrence_weights_are_retained_in_simhash(self):
        a = self.api.simhash_target('alpha beta gamma delta')
        b = self.api.simhash_target('alpha beta gamma alpha beta gamma alpha beta gamma delta')
        self.assertNotEqual(a, b)
