import unittest
from src.bedrock.model_json import parse_object, ModelOutputFormatError


class ModelJsonTests(unittest.TestCase):
    def test_plain_and_fenced_json_are_equivalent(self):
        for text in ('{"question":"확인"}', '```json\n{"question":"확인"}\n```', '\ufeff {"question":"확인"} '):
            self.assertEqual(parse_object(text, {}), {"question": "확인"})

    def test_prose_trailing_data_duplicates_and_nonobjects_rejected(self):
        for text in ('설명 {"a":1}', '{"a":1} trailing', '[]', '{"a":1,"a":2}', '{"a":NaN}'):
            with self.subTest(text=text), self.assertRaises(ModelOutputFormatError):
                parse_object(text, {})

    def test_usage_survives_format_failure(self):
        usage = {"input_tokens": 30, "output_tokens": 9}
        with self.assertRaises(ModelOutputFormatError) as result:
            parse_object('not JSON', usage)
        self.assertEqual(result.exception.usage, usage)
