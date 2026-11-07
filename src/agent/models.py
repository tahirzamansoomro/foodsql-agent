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
