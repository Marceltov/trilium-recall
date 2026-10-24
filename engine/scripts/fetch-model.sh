#!/bin/bash
# Download the pinned multilingual-e5-small int8 ONNX model and its tokenizer
# into <dest> (model.onnx + sentencepiece.bpe.model) and verify their checksums.
# Usage: scripts/fetch-model.sh <dest>
set -euo pipefail

dest="${1:?usage: fetch-model.sh <dest>}"
# The int8 ONNX export comes from Xenova; the tokenizer from the original model
# (same ids as tokenizer.json, a fraction of the memory).
onnx_base="https://huggingface.co/Xenova/multilingual-e5-small/resolve/761b726dd34fb83930e26aab4e9ac3899aa1fa78"
sp_base="https://huggingface.co/intfloat/multilingual-e5-small/resolve/614241f622f53c4eeff9890bdc4f31cfecc418b3"

mkdir -p "$dest"
curl -sfL --retry 3 -o "$dest/model.onnx" "$onnx_base/onnx/model_quantized.onnx"
curl -sfL --retry 3 -o "$dest/sentencepiece.bpe.model" "$sp_base/sentencepiece.bpe.model"

cd "$dest"
sha256sum -c - <<SUMS
f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193  model.onnx
cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865  sentencepiece.bpe.model
SUMS
