import unittest
from pathlib import Path


class AuthenticationQuerySyntaxTests(unittest.TestCase):
    def test_authentication_queries_do_not_insert_spaces_around_equals(self):
        source = (Path(__file__).parents[1] / "pyaarlo" / "backend.py").read_text()

        self.assertIn('AUTH_GET_FACTORS + "?data={}".format(int(time.time()))', source)
        self.assertIn('AUTH_VALIDATE_PATH + "?data={}".format(int(time.time()))', source)
        self.assertNotIn('AUTH_GET_FACTORS + "?data = {}"', source)
        self.assertNotIn('AUTH_VALIDATE_PATH + "?data = {}"', source)


if __name__ == "__main__":
    unittest.main()
