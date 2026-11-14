"""
FoodSQL-Agent  |  Model wrappers

Every model has the same method:  generate(messages) -> dict with
    text, latency_s, input_tokens, output_tokens, cost_usd
so the agent and the evaluation do not care which model is behind it.

    OpenAIModel : GPT-4o through the API (costs money, needs OPENAI_API_KEY in .env)
    HFModel     : a local Hugging Face model such as Qwen2.5-Coder, loaded in 4-bit,
                  optionally with a QLoRA adapter (the fine-tuned version)
"""

import os
import time

# GPT-4o price in USD per 1 million tokens. Check the OpenAI pricing page before the final run.
GPT4O_INPUT_PER_M = 2.50
GPT4O_OUTPUT_PER_M = 10.00

# Gemini paid-tier list prices in USD per 1 million tokens (input, output). The free tier costs
# nothing, so cost is reported at LIST PRICE to keep the comparison with other models meaningful.
# Check the Google AI Studio pricing page before the final run.
GEMINI_PRICES = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.6-flash": (0.75, 3.75),
}
DEFAULT_GEMINI_PRICE = (0.30, 2.50)


class ChatModel:
    name = "model"

    def generate(self, messages: list) -> dict:
        raise NotImplementedError


class OpenAIModel(ChatModel):
    def __init__(self, model: str = "gpt-4o", max_tokens: int = 400):
        from dotenv import load_dotenv
        from openai import OpenAI

        load_dotenv()
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set. Put it in the .env file.")
        self.client = OpenAI()
        self.model = model
        self.max_tokens = max_tokens
        self.name = model

    def generate(self, messages: list) -> dict:
        start = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=0, max_tokens=self.max_tokens)
        latency = time.perf_counter() - start
        usage = response.usage
        cost = (usage.prompt_tokens * GPT4O_INPUT_PER_M
                + usage.completion_tokens * GPT4O_OUTPUT_PER_M) / 1_000_000
        return {
            "text": response.choices[0].message.content or "",
            "latency_s": latency,
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
            "cost_usd": cost,
        }


class GeminiModel(ChatModel):
    """
    Gemini through the Google AI Studio API (needs GEMINI_API_KEY in .env).
    The free tier has request limits (requests per minute and per day), so requests are
    spaced out automatically and temporary errors are retried.
    """

    def __init__(self, model: str = "gemini-3.5-flash-lite", rpm: int = 8,
                 max_tokens: int = 400, client=None):
        if client is None:
            from dotenv import load_dotenv
            from google import genai

            load_dotenv()
            key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if not key:
                raise RuntimeError("GEMINI_API_KEY is not set. Put it in the .env file.")
            client = genai.Client(api_key=key)
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.min_interval = 60.0 / rpm
        self._last_call = 0.0
        self.name = model

    @staticmethod
    def convert(messages: list):
        """Our chat messages -> (system text, Gemini 'contents')."""
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages if m["role"] != "system"
        ]
        return system, contents

    def generate(self, messages: list) -> dict:
        system, contents = self.convert(messages)
        config = {"temperature": 0, "max_output_tokens": self.max_tokens}
        if system:
            config["system_instruction"] = system

        for attempt in range(1, 7):
            pause = self.min_interval - (time.monotonic() - self._last_call)
            if pause > 0:
                time.sleep(pause)   # stay below the free-tier requests-per-minute limit
            self._last_call = time.monotonic()
            start = time.perf_counter()
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=contents, config=config)
                latency = time.perf_counter() - start   # only the API call, not the waiting
                break
            except Exception as exc:
                lowered = str(exc).lower()
                if "perday" in lowered or "per day" in lowered:
                    raise RuntimeError("Gemini daily free limit reached. Try again tomorrow "
                                       "or use another model.") from exc
                temporary = any(k in lowered for k in ("429", "resource_exhausted", "500", "503",
                                                       "unavailable", "overloaded"))
                if not temporary or attempt == 6:
                    raise
                time.sleep(15 * attempt)

        usage = response.usage_metadata
        n_in = getattr(usage, "prompt_token_count", 0) or 0
        n_out = (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)
        price_in, price_out = GEMINI_PRICES.get(self.model, DEFAULT_GEMINI_PRICE)
        return {
            "text": response.text or "",
            "latency_s": latency,
            "input_tokens": n_in,
            "output_tokens": n_out,
            "cost_usd": (n_in * price_in + n_out * price_out) / 1_000_000,
        }


class HFModel(ChatModel):
    """Local model in 4-bit (NF4). Pass adapter_path to load a QLoRA adapter on top."""

    def __init__(self, model_id: str, adapter_path: str = None, max_new_tokens: int = 300):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        self.torch = torch
        self.max_new_tokens = max_new_tokens
        self.name = model_id.split("/")[-1] + ("+lora" if adapter_path else "")

        bnb = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True)
        self.tokenizer = AutoTokenizer.from_pretrained(adapter_path or model_id)

        kwargs = dict(quantization_config=bnb, device_map={"": 0})
        try:  # newer transformers versions call this argument "dtype"
            model = AutoModelForCausalLM.from_pretrained(model_id, dtype=torch.float16, **kwargs)
        except TypeError:
            model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float16, **kwargs)

        if adapter_path:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, adapter_path)
        model.eval()
        self.model = model

    def generate(self, messages: list) -> dict:
        torch = self.torch
        text = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
        n_in = inputs["input_ids"].shape[1]

        torch.cuda.synchronize()
        start = time.perf_counter()
        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens, do_sample=False)
        torch.cuda.synchronize()
        latency = time.perf_counter() - start

        new_tokens = out[0][n_in:]
        return {
            "text": self.tokenizer.decode(new_tokens, skip_special_tokens=True),
            "latency_s": latency,
            "input_tokens": int(n_in),
            "output_tokens": int(new_tokens.shape[0]),
            "cost_usd": 0.0,   # runs on our own GPU
        }
