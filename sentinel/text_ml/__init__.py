"""Learned SMS scam-text model: ham / spam / smishing.

Pipeline: `source` (verified acquisition and audit) -> `splits` (template-grouped,
stratified train/calibration/test) -> `training` (transformer fine-tuning,
temperature calibration, single test evaluation, ONNX export) -> `service`
(checked artifact loading, inference and word-level explanations).
Only `service` is imported by the app, and it needs only onnxruntime, tokenizers
and numpy.
"""

LABELS = ("ham", "spam", "smishing")
