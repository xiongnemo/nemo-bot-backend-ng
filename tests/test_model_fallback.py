import unittest
from nemollm.registry import ModelRegistry
from nemollm.base import BaseLLMClient

class MockClient(BaseLLMClient):
    def __init__(self, name="mock"):
        super().__init__(base_url="http://mock", api_key="mock")
        self.name = name

    def chat(self, *args, **kwargs):
        pass

class TestModelFallback(unittest.TestCase):
    def setUp(self):
        self.config = {
            "models": [
                "openai:model-a",
                "openai:model-b",
                "openai:model-c"
            ],
            "providers": {
                "openai": {
                    "type": "openai",
                    "api_key": "test"
                }
            }
        }
        self.registry = ModelRegistry(self.config)
        # Override providers with mock clients for clean testing
        self.client_a = MockClient("a")
        self.client_b = MockClient("b")
        self.client_c = MockClient("c")
        self.registry.providers["openai"] = self.client_a # all point to client_a in basic lookup

    def test_fallback_promotion(self):
        models = self.registry.get_models()
        self.assertEqual(len(models), 3)
        self.assertEqual(models[0][1], "model-a")
        self.assertEqual(models[1][1], "model-b")
        self.assertEqual(models[2][1], "model-c")

        # Report success on model-b (index 1)
        self.registry.report_success(models[1][0], "model-b")

        # Now get_models should start with model-b
        promoted_models = self.registry.get_models()
        self.assertEqual(promoted_models[0][1], "model-b")
        self.assertEqual(promoted_models[1][1], "model-c")
        self.assertEqual(promoted_models[2][1], "model-a")

        # Report success on model-a (index 0 originally, now index 2 in promoted list)
        self.registry.report_success(promoted_models[2][0], "model-a")

        # Now get_models should be back to model-a first
        restored_models = self.registry.get_models()
        self.assertEqual(restored_models[0][1], "model-a")
        self.assertEqual(restored_models[1][1], "model-b")
        self.assertEqual(restored_models[2][1], "model-c")

if __name__ == "__main__":
    unittest.main()
