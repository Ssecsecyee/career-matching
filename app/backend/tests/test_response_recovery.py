import unittest
from src.services.dependency_errors import dependency_error
from src.bedrock.model_json import ModelOutputFormatError,ModelOutputTruncatedError
class ResponseRecoveryTests(unittest.TestCase):
 def test_format_failure_invites_next_step_without_claiming_success(self):
  status,data=dependency_error(ModelOutputFormatError({}))
  self.assertEqual(status,502);self.assertEqual(data['status'],'model_response_needs_clarification');self.assertFalse(data['retryable']);self.assertIn('기존 대화와 답변은 유지',data['message'])
 def test_truncation_remains_distinct(self):
  _,data=dependency_error(ModelOutputTruncatedError({}));self.assertEqual(data['status'],'model_output_truncated')
