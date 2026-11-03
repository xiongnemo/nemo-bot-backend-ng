import unittest
from unittest.mock import MagicMock, patch
import json

from nemollm.base import (
    parse_model_and_effort,
    map_effort_to_anthropic_budget,
    map_effort_to_gemini_budget,
)
from nemollm.registry import ModelRegistry
from nemollm.openai_client import OpenAIClient
from nemollm.openai_responses_client import OpenAIResponsesClient
from nemollm.anthropic_client import AnthropicClient
from nemollm.gemini_client import GeminiClient
from nemollm.types import ChatMessage


class TestModelThinkingEffort(unittest.TestCase):
    def test_parse_model_and_effort(self):
        # 1. Standard effort keywords
        self.assertEqual(parse_model_and_effort("glm-5.3:medium"), ("glm-5.3", "medium"))
        self.assertEqual(parse_model_and_effort("glm-5.3:max"), ("glm-5.3", "max"))
        self.assertEqual(parse_model_and_effort("glm-5.3:ultra"), ("glm-5.3", "ultra"))
        self.assertEqual(parse_model_and_effort("glm-5.3:xhigh"), ("glm-5.3", "xhigh"))
        self.assertEqual(parse_model_and_effort("o3-mini:extra_high"), ("o3-mini", "extra_high"))
        self.assertEqual(parse_model_and_effort("o3-mini:high"), ("o3-mini", "high"))
        self.assertEqual(parse_model_and_effort("gemini-2.5-pro:low"), ("gemini-2.5-pro", "low"))
        self.assertEqual(parse_model_and_effort("claude-3-7-sonnet:none"), ("claude-3-7-sonnet", "none"))
        self.assertEqual(parse_model_and_effort("claude-3-7-sonnet:off"), ("claude-3-7-sonnet", "off"))
        self.assertEqual(parse_model_and_effort("claude-3-7-sonnet:disabled"), ("claude-3-7-sonnet", "disabled"))

        # 2. Integer token budget
        self.assertEqual(parse_model_and_effort("claude-3-7-sonnet:4096"), ("claude-3-7-sonnet", "4096"))
        self.assertEqual(parse_model_and_effort("gemini-2.5-flash:8192"), ("gemini-2.5-flash", "8192"))

        # 3. Model strings with tags or variants that should NOT be stripped
        self.assertEqual(parse_model_and_effort("llama3:8b"), ("llama3:8b", None))
        self.assertEqual(parse_model_and_effort("deepseek-r1:14b"), ("deepseek-r1:14b", None))
        self.assertEqual(parse_model_and_effort("qwen2.5:72b"), ("qwen2.5:72b", None))
        self.assertEqual(parse_model_and_effort("gpt-4o:nitro"), ("gpt-4o:nitro", None))
        self.assertEqual(parse_model_and_effort("meta-llama/llama-3.3-70b-instruct:free"), ("meta-llama/llama-3.3-70b-instruct:free", None))
        self.assertEqual(parse_model_and_effort("mistralai/mistral-large:exacto"), ("mistralai/mistral-large:exacto", None))

        # 4. Multi-colon strings: openrouter free variant with effort suffix
        self.assertEqual(
            parse_model_and_effort("google/gemini-2.0-flash:free:high"),
            ("google/gemini-2.0-flash:free", "high")
        )

        # 5. Plain models without colon
        self.assertEqual(parse_model_and_effort("gpt-4o"), ("gpt-4o", None))
        self.assertEqual(parse_model_and_effort("glm-5.2"), ("glm-5.2", None))

    def test_registry_parsing_with_and_without_provider(self):
        config = {
            "models": [
                "nemo-axonhub-openai:glm-5.3:medium",
                "glm-5.3:high",
                "nemo-axonhub-anthropic:claude-sonnet-5:4096",
            ],
            "providers": {
                "nemo-axonhub-openai": {"type": "openai", "api_key": "k1"},
                "nemo-axonhub-anthropic": {"type": "anthropic", "api_key": "k2"},
                "openai": {"type": "openai", "api_key": "k3"},
            }
        }
        reg = ModelRegistry(config)
        models = reg.get_models()
        self.assertEqual(len(models), 3)

        # 1. nemo-axonhub-openai:glm-5.3:medium
        c1, m1 = models[0]
        self.assertIsInstance(c1, OpenAIClient)
        self.assertEqual(m1, "glm-5.3:medium")

        # 2. glm-5.3:high (no provider, defaults to openai)
        c2, m2 = models[1]
        self.assertIsInstance(c2, OpenAIClient)
        self.assertEqual(m2, "glm-5.3:high")

        # 3. nemo-axonhub-anthropic:claude-sonnet-5:4096
        c3, m3 = models[2]
        self.assertIsInstance(c3, AnthropicClient)
        self.assertEqual(m3, "claude-sonnet-5:4096")

    @patch("requests.post")
    def test_openai_client_glm_and_reasoning_payload(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Hello world",
                    "reasoning_content": "Deep reasoning step 1... step 2..."
                },
                "finish_reason": "stop"
            }],
            "usage": {"total_tokens": 120}
        }
        mock_post.return_value = mock_resp

        client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="test-key")

        # 1. GLM 5.3 with medium effort
        resp = client.chat(
            model="glm-5.3:medium",
            messages=[ChatMessage(role="user", content="Hello")]
        )
        self.assertEqual(resp.text, "Hello world")
        self.assertEqual(resp.thinking, "Deep reasoning step 1... step 2...")

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["model"], "glm-5.3")
        self.assertEqual(sent_payload["reasoning_effort"], "medium")
        self.assertEqual(sent_payload["thinking"], {"type": "enabled"})

        # 2. GLM 5.3 without effort suffix: auto-defaults reasoning_effort to "high"
        resp2 = client.chat(
            model="glm-5.3",
            messages=[ChatMessage(role="user", content="Hello")]
        )
        sent_payload2 = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload2["model"], "glm-5.3")
        self.assertEqual(sent_payload2["reasoning_effort"], "high")
        self.assertEqual(sent_payload2["thinking"], {"type": "enabled"})

        # 3. o3-mini with high effort
        client.chat(
            model="o3-mini:high",
            messages=[ChatMessage(role="user", content="Math problem")]
        )
        sent_payload3 = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload3["model"], "o3-mini")
        self.assertEqual(sent_payload3["reasoning_effort"], "high")
        self.assertNotIn("thinking", sent_payload3)

        # 4. gpt-4o without effort
        client.chat(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content="Hi")]
        )
        sent_payload4 = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload4["model"], "gpt-4o")
        self.assertNotIn("reasoning_effort", sent_payload4)
        self.assertNotIn("thinking", sent_payload4)

    @patch("requests.post")
    def test_openai_responses_client_payload(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "output": [
                {"type": "reasoning", "content": "I am thinking about the code..."},
                {"type": "message", "content": [{"type": "text", "text": "Here is the code."}]}
            ]
        }
        mock_post.return_value = mock_resp

        client = OpenAIResponsesClient(base_url="https://api.openai.com/v1", api_key="test-key")
        resp = client.chat(
            model="glm-5.3:max",
            messages=[ChatMessage(role="user", content="Code review")]
        )

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["model"], "glm-5.3")
        self.assertEqual(sent_payload["reasoning"], {"effort": "max"})
        self.assertEqual(sent_payload["thinking"], {"type": "enabled"})
        self.assertEqual(resp.text, "Here is the code.")
        self.assertEqual(resp.thinking, "I am thinking about the code...")

    @patch("requests.post")
    def test_anthropic_client_payload_and_rules(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": [
                {"type": "thinking", "thinking": "Internal thought process..."},
                {"type": "text", "text": "Anthropic response"}
            ],
            "stop_reason": "end_turn"
        }
        mock_post.return_value = mock_resp

        client = AnthropicClient(base_url="https://api.anthropic.com", api_key="test-key", default_temperature=0.7)

        # 1. Effort string "high" -> 8192 tokens budget
        # Temp should be stripped, max_tokens increased if needed
        resp = client.chat(
            model="claude-3-7-sonnet:high",
            messages=[ChatMessage(role="user", content="Solve this")]
        )
        self.assertEqual(resp.text, "Anthropic response")
        self.assertEqual(resp.thinking, "Internal thought process...")

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["model"], "claude-3-7-sonnet")
        self.assertEqual(sent_payload["thinking"], {"type": "enabled", "budget_tokens": 8192})
        self.assertGreater(sent_payload["max_tokens"], 8192)
        self.assertNotIn("temperature", sent_payload)

        # 2. Effort string integer "4096"
        client.chat(
            model="claude-3-7-sonnet:4096",
            messages=[ChatMessage(role="user", content="Solve this")]
        )
        sent_payload2 = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload2["thinking"], {"type": "enabled", "budget_tokens": 4096})

        # 3. Effort "ultra" -> 32768
        client.chat(
            model="claude-3-7-sonnet:ultra",
            messages=[ChatMessage(role="user", content="Ultra deep thinking")]
        )
        sent_payload_ultra = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload_ultra["thinking"], {"type": "enabled", "budget_tokens": 32768})

        # 4. Effort "xhigh" -> 16384
        client.chat(
            model="claude-3-7-sonnet:xhigh",
            messages=[ChatMessage(role="user", content="Extra high thinking")]
        )
        sent_payload_xhigh = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload_xhigh["thinking"], {"type": "enabled", "budget_tokens": 16384})

        # 5. Effort "none" -> disabled
        client.chat(
            model="claude-3-7-sonnet:none",
            messages=[ChatMessage(role="user", content="Solve this")]
        )
        sent_payload3 = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload3["thinking"], {"type": "disabled"})

    @patch("requests.post")
    def test_gemini_client_payload_and_thought_parsing(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [
                        {"thought": True, "text": "Analyzing query...\n"},
                        {"text": "Final Gemini answer"}
                    ]
                },
                "finishReason": "STOP"
            }]
        }
        mock_post.return_value = mock_resp

        client = GeminiClient(base_url="https://generativelanguage.googleapis.com", api_key="test-key")

        resp = client.chat(
            model="gemini-2.5-pro:medium",
            messages=[ChatMessage(role="user", content="Explain quantum physics")]
        )

        sent_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload["generationConfig"]["thinkingConfig"], {"thinkingBudget": 4096})
        self.assertEqual(resp.text, "Final Gemini answer")
        self.assertEqual(resp.thinking, "Analyzing query...")

        # Effort 0 / disabled
        client.chat(
            model="gemini-2.5-flash:off",
            messages=[ChatMessage(role="user", content="Hi")]
        )
        sent_payload2 = mock_post.call_args.kwargs["json"]
        self.assertEqual(sent_payload2["generationConfig"]["thinkingConfig"], {"thinkingBudget": 0})


if __name__ == "__main__":
    unittest.main()
