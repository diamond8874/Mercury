"""Regression checks for rounding parameter validation without Flask startup."""
import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from services.cleaning.engine import run_cleaning_engine
from services.cleaning.schema import parse_typed_operation


class TypedRoundingValidationTests(unittest.TestCase):
    def test_malformed_decimals_are_rejected(self):
        for operation in ('round_numeric', 'round_values'):
            for value in ('invalid', None, [], {}, float('inf')):
                for nested in (False, True):
                    with self.subTest(operation=operation, value=value, nested=nested):
                        payload = {'operation': operation}
                        payload.update({'parameters': {'decimals': value}} if nested else {'decimals': value})
                        self.assertIsNone(parse_typed_operation(payload, 'Age'))

    def test_valid_decimals_preserve_normalization(self):
        for value, expected in ((0, 0), ('0', 0), (2, 2), ('2', 2), (-1, -1), ('-1', -1)):
            for nested in (False, True):
                with self.subTest(value=value, nested=nested):
                    payload = {'operation': 'round_numeric'}
                    payload.update({'parameters': {'decimals': value}} if nested else {'decimals': value})
                    parsed = parse_typed_operation(payload, 'Age')
                    self.assertIsNotNone(parsed)
                    self.assertEqual(parsed.to_plan_dict()['parameters']['decimals'], expected)
                    self.assertEqual(parsed.column, 'Age')

    def test_engine_warns_and_preserves_data_for_invalid_rounding(self):
        original = pd.DataFrame({'Age': [1.234, float('nan')]})
        result = run_cleaning_engine(original, {
            'Age': {'action': 'transform', 'operations': [
                {'operation': 'round_numeric', 'decimals': 'invalid'}
            ]}
        })
        self.assertTrue(result['warnings'])
        assert_frame_equal(result['df'], original)

    def test_engine_still_executes_valid_rounding(self):
        original = pd.DataFrame({'Age': [1.234, float('nan')]})
        result = run_cleaning_engine(original, {
            'Age': {'action': 'transform', 'operations': [
                {'operation': 'round_numeric', 'decimals': '2'}
            ]}
        })
        self.assertEqual(result['df']['Age'].iloc[0], 1.23)
        self.assertTrue(pd.isna(result['df']['Age'].iloc[1]))
        self.assertEqual(original['Age'].iloc[0], 1.234)
        self.assertFalse(result['errors'])


if __name__ == '__main__':
    unittest.main()
