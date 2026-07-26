import unittest
from asteval import Interpreter


class TestGetattrSecurity(unittest.TestCase):
    def test_getattr_blocked(self):
        aeval = Interpreter()
        aeval("getattr('', '__class__')")
        self.assertGreater(len(aeval.error), 0)


if __name__ == "__main__":
    unittest.main()
