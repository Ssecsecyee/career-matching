import unittest
from src.services.admin_auth import authenticate
class PublicAccessTests(unittest.TestCase):
 def test_public_is_opt_in_and_user_only(self):
  h={'X-Client-Token':'c'*64}
  self.assertIsNone(authenticate(h,'u'*32,'a'*32))
  identity=authenticate(h,'u'*32,'a'*32,allow_public=True)
  self.assertEqual(identity[2],'user')
  self.assertEqual(identity[0],authenticate({**h,'Authorization':'Bearer '+'u'*32},'u'*32,'a'*32)[0])
 def test_invalid_credentials_never_fall_back_to_public(self):
  self.assertIsNone(authenticate({'X-Client-Token':'c'*64,'Authorization':'Bearer wrong'},'u'*32,'a'*32,allow_public=True))
  self.assertIsNone(authenticate({},'u'*32,'a'*32,allow_public=True))
 def test_admin_still_requires_its_secret(self):
  self.assertEqual(authenticate({'X-Client-Token':'c'*64,'Authorization':'Bearer '+'a'*32},'u'*32,'a'*32,allow_public=True)[2],'admin')
