"""
FoodSQL-Agent  |  QLoRA fine-tuning of Qwen2.5-Coder on the food-delivery training set

QLoRA = the base model is loaded in 4-bit (small memory) and only small LoRA adapters
are trained. The loss is computed ONLY on the SQL answer, not on the prompt.

The training prompt is built with the same build_messages() function that the agent
uses at test time, so training and testing see identical prompts.

A plain PyTorch loop is used on purpose (no TRL / Trainer): it depends on very few
library features, so it keeps working when those libraries change their APIs.

Examples (run from the repository root):

    # Quick smoke test on the local GPU with a small model (about 5 minutes)
    python src/finetune/train_qlora.py --model-id Qwen/Qwen2.5-Coder-1.5B-Instruct --limit 16 --epochs 1 --out outputs/smoke

    # Real training on Kaggle (T4 16 GB)
    python src/finetune/train_qlora.py --model-id Qwen/Qwen2.5-Coder-7B-Instruct --epochs 2 --out outputs/qwen7b-lora
"""

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # makes "src" importable

from src.agent.prompts import build_messages
from src.agent.schema import DEFAULT_SCHEMA_PATH, load_schema

TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def encode_example(tokenizer, schema, question, sql, max_len):
    """
    Turn one (question, SQL) pair into token ids and labels.
    Labels are -100 (ignored by the loss) for the prompt and real ids for the SQL answer.
    Returns None if the example cannot be encoded safely.
    """
    messages = build_messages(schema, question)
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    full = tokenizer.apply_chat_template(
        messages + [{"role": "assistant", "content": sql}], tokenize=False)
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    full_ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    if full_ids[: len(prompt_ids)] != prompt_ids or len(full_ids) > max_len:
        return None
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]
    if all(label == -100 for label in labels):
        return None
    return full_ids, labels


def main():
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    p = argparse.ArgumentParser()
    p.add_argument("--model-id", default="Qwen/Qwen2.5-Coder-7B-Instruct")
    p.add_argument("--train", default="datasets/text2sql/train.jsonl")
    p.add_argument("--schema", default=str(DEFAULT_SCHEMA_PATH))
    p.add_argument("--out", default="outputs/qwen-lora")
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--max-len", type=int, default=1536)
    p.add_argument("--lora-r", type=int, default=16)
    p.add_argument("--lora-alpha", type=int, default=32)
    p.add_argument("--limit", type=int, default=None, help="use only the first N training pairs (smoke test)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--wandb", action="store_true", help="log the loss to Weights & Biases")
    args = p.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- data ----
    schema = load_schema(args.schema)
    with open(args.train, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    if args.limit:
        records = records[: args.limit]

    tokenizer = AutoTokenizer.from_pretrained(args.model_id)
    examples, skipped = [], 0
    for r in records:
        enc = encode_example(tokenizer, schema, r["question"], r["sql"], args.max_len)
        if enc is None:
            skipped += 1
        else:
            examples.append(enc)
    lengths = [len(ids) for ids, _ in examples]
    print(f"[Data] {len(examples)} examples ({skipped} skipped) | tokens per example: "
          f"avg {sum(lengths) // max(1, len(lengths))}, max {max(lengths)}")
    if not examples:
        raise SystemExit("No usable training examples.")

    # ---- model (4-bit) + LoRA ----
    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True)
    kwargs = dict(quantization_config=bnb, device_map={"": 0})
    try:  # newer transformers versions call this argument "dtype"
        model = AutoModelForCausalLM.from_pretrained(args.model_id, dtype=torch.float16, **kwargs)
    except TypeError:
        model = AutoModelForCausalLM.from_pretrained(args.model_id, torch_dtype=torch.float16, **kwargs)
    model.config.use_cache = False

    try:
        model = prepare_model_for_kbit_training(
            model, use_gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False})
    except TypeError:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    lora = LoraConfig(r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=0.05,
                      target_modules=TARGET_MODULES, bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0)
    try:
        scaler = torch.amp.GradScaler("cuda")
    except (AttributeError, TypeError):
        scaler = torch.cuda.amp.GradScaler()

    total_updates = math.ceil(len(examples) * args.epochs / args.grad_accum)
    warmup = max(1, int(0.05 * total_updates))

    def lr_at(update):  # short warm-up, then cosine decay
        if update < warmup:
            return args.lr * (update + 1) / warmup
        progress = (update - warmup) / max(1, total_updates - warmup)
        return args.lr * 0.5 * (1 + math.cos(math.pi * progress))

    if args.wandb:
        import wandb
        wandb.init(project="foodsql-agent", name=out_dir.name, config=vars(args))

    # ---- training loop ----
    model.train()
    log, pending, update, running, start = [], 0, 0, [], time.time()

    def optimizer_step():
        nonlocal pending, update
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        for group in optimizer.param_groups:
            group["lr"] = lr_at(update)
        scaler.step(optimizer)
        scaler.update()
        optimizer.zero_grad(set_to_none=True)
        pending = 0
        update += 1
        if update % 5 == 0 or update == total_updates:
            avg = sum(running) / len(running)
            running.clear()
            elapsed = time.time() - start
            print(f"update {update}/{total_updates} | loss {avg:.4f} | lr {lr_at(update):.2e} | {elapsed / 60:.1f} min")
            log.append({"update": update, "loss": avg, "minutes": elapsed / 60})
            if args.wandb:
                wandb.log({"loss": avg, "lr": lr_at(update)}, step=update)

    for epoch in range(1, args.epochs + 1):
        order = list(range(len(examples)))
        random.shuffle(order)
        for i in order:
            ids, labels = examples[i]
            input_ids = torch.tensor([ids], device="cuda")
            label_ids = torch.tensor([labels], device="cuda")
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                out = model(input_ids=input_ids, attention_mask=torch.ones_like(input_ids), labels=label_ids)
            scaler.scale(out.loss / args.grad_accum).backward()
            running.append(out.loss.item())
            pending += 1
            if pending == args.grad_accum:
                optimizer_step()
        if pending:  # leftover examples at the end of the epoch
            optimizer_step()
        model.save_pretrained(out_dir / f"epoch{epoch}")
        print(f"[Saved] {out_dir / f'epoch{epoch}'}")

    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    (out_dir / "train_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"\n[Done] adapter saved in {out_dir} | total time {(time.time() - start) / 60:.1f} min")


if __name__ == "__main__":
    main()
