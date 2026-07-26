import unittest
from asteval import Interpreter


class TestAsteval(unittest.TestCase):
    def setUp(self):
        self.aeval = Interpreter()

    def test_basic_math(self):
        res = self.aeval("1 + 2 * 3")
        self.assertEqual(res, 7)
        self.assertEqual(len(self.aeval.error), 0)

    def test_os_system_blocked(self):
        self.aeval("import os; os.system('calc')")
        self.assertGreater(len(self.aeval.error), 0)


if __name__ == "__main__":
    unittest.main()
