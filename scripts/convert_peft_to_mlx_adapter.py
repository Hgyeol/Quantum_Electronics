"""Convert a Hugging Face PEFT LoRA adapter to MLX-LM format.

PEFT and MLX-LM use different on-disk layouts for LoRA adapters. The
training artifact produced by `notebooks/dpo_qwen_colab.ipynb` is in PEFT
format, but the local inference path on Apple Silicon uses MLX-LM, which
expects:

- `adapters.safetensors` (not `adapter_model.safetensors`)
- weight keys `model.layers.{i}.<module>.lora_{a,b}` (not the PEFT
  `base_model.model.model.layers.{i}.<module>.lora_{A,B}.default.weight`)
- `lora_a` shape `(in_features, r)` and `lora_b` shape `(r, out_features)`
  — both transposed relative to PEFT
- `adapter_config.json` with `fine_tune_type`, `num_layers`,
  `lora_parameters` keys instead of PEFT's schema

Reads a PEFT adapter directory and writes a sibling directory in MLX-LM
format suitable for `mlx_lm.load(..., adapter_path=...)`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import torch
from safetensors import safe_open
from safetensors.torch import save_file

_PEFT_KEY_RE = re.compile(
    r"^base_model\.model\.model\.layers\.(\d+)\.(.+)\.lora_([AB])\.(?:default\.)?weight$"
)


def convert_weights(src: Path, dst: Path) -> tuple[int, set[str], int]:
    """Rename + transpose PEFT LoRA weights into MLX-LM layout.

    Returns (num_pairs, target_module_keys, max_layer_index).
    """
    tensors: dict = {}
    keys_seen: set[str] = set()
    max_layer = -1
    with safe_open(str(src), framework="pt") as f:
        for peft_key in f.keys():
            m = _PEFT_KEY_RE.match(peft_key)
            if not m:
                raise ValueError(f"Unexpected PEFT key (no match): {peft_key}")
            layer_idx, module_path, ab = m.group(1), m.group(2), m.group(3)
            max_layer = max(max_layer, int(layer_idx))
            keys_seen.add(module_path)
            tensor = f.get_tensor(peft_key)
            # PEFT lora_A: (r, in_features) -> MLX lora_a: (in_features, r)
            # PEFT lora_B: (out_features, r) -> MLX lora_b: (r, out_features)
            # Cast to float16: MLX-LM's q4 base computes in fp16, so adapter
            # weights need to match to avoid promotion churn.
            tensor_t = tensor.T.contiguous().to(torch.float16)
            mlx_key = f"model.layers.{layer_idx}.{module_path}.lora_{ab.lower()}"
            tensors[mlx_key] = tensor_t
    save_file(tensors, str(dst))
    return len(tensors) // 2, keys_seen, max_layer


def build_mlx_adapter_config(peft_config: dict, target_keys: set[str], num_layers: int) -> dict:
    r = peft_config["r"]
    alpha = peft_config["lora_alpha"]
    dropout = peft_config.get("lora_dropout", 0.0)
    return {
        "fine_tune_type": "lora",
        "num_layers": num_layers,
        "lora_parameters": {
            "rank": r,
            "scale": alpha / r,
            "dropout": dropout,
            "keys": sorted(target_keys),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--src",
        default="ml/artifacts/llm_dpo_v1",
        help="PEFT adapter directory (contains adapter_model.safetensors + adapter_config.json)",
    )
    parser.add_argument(
        "--dst",
        default="ml/artifacts/llm_dpo_v1_mlx",
        help="Output directory for MLX-LM compatible adapter",
    )
    args = parser.parse_args()

    src_dir = Path(args.src)
    dst_dir = Path(args.dst)
    dst_dir.mkdir(parents=True, exist_ok=True)

    src_cfg_path = src_dir / "adapter_config.json"
    src_weights_path = src_dir / "adapter_model.safetensors"
    if not src_cfg_path.exists() or not src_weights_path.exists():
        raise SystemExit(f"Missing PEFT adapter files under {src_dir}")

    with open(src_cfg_path) as f:
        peft_config = json.load(f)

    pairs, target_keys, max_layer = convert_weights(
        src_weights_path, dst_dir / "adapters.safetensors"
    )

    mlx_cfg = build_mlx_adapter_config(peft_config, target_keys, num_layers=max_layer + 1)
    with open(dst_dir / "adapter_config.json", "w") as f:
        json.dump(mlx_cfg, f, indent=2)

    print(f"[convert] {pairs} LoRA pairs, layers 0..{max_layer}, keys={sorted(target_keys)}")
    print(f"[convert] wrote {dst_dir}/adapters.safetensors")
    print(f"[convert] wrote {dst_dir}/adapter_config.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
