import unittest
from asteval import Interpreter


class TestAstevalSecurity(unittest.TestCase):
    def setUp(self):
        self.aeval = Interpreter()

    def test_class_access_blocked(self):
        self.aeval("''.__class__")
        self.assertGreater(len(self.aeval.error), 0)

    def test_subclasses_access_blocked(self):
        self.aeval("().__class__.__bases__[0].__subclasses__()")
        self.assertGreater(len(self.aeval.error), 0)


if __name__ == "__main__":
    unittest.main()
