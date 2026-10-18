# embeddings.py — searching documents by meaning, entirely on this Mac.
#
# A small multilingual sentence model (multilingual-e5-small, 8-bit, ONNX) turns each passage and each question into
# 384 numbers; passages whose numbers point the same way as the question's are about the same thing, even when they
# share no words - "How much do I put down up front for the flat?" finds "a security deposit equal to two monthly
# rents", and a Bulgarian question finds an English passage. The model (135 MB) is downloaded once, on request,
# from a pinned revision and checked against its SHA-256; without it NOVA searches by words alone.
# (Apple's built-in NaturalLanguage embeddings were tried first and found only 6 of 12 reworded questions; this
# model finds 11 of 12 - see tests/meaning_corpus.py.)
import os, logging, threading
import paths

log = logging.getLogger("nova")

MODEL_NAME = "multilingual-e5-small"
REVISION   = "761b726dd34fb83930e26aab4e9ac3899aa1fa78"
BASE_URL   = f"https://huggingface.co/Xenova/multilingual-e5-small/resolve/{REVISION}/"
FILES = {   # local name: (path in the repository, SHA-256, bytes)
    "model_quantized.onnx": ("onnx/model_quantized.onnx",
                             "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193", 118308185),
    "tokenizer.json":       ("tokenizer.json",
                             "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39", 17082730),
}
MODEL_MB = 135
MODEL_ID = f"{MODEL_NAME}-q8@{REVISION[:7]}"      # stored with the vectors: other vectors are made again
DIM = 384
MAX_TOKENS = 512
BATCH = 16

_model = None
_model_lock = threading.Lock()


class EmbeddingError(Exception):
    pass


def model_dir() -> str:
    return os.environ.get("NOVA_MEANING_MODEL") or os.path.join(paths.DATA_DIR, "models", MODEL_NAME)


def runtime_installed() -> bool:
    import importlib.util
    try:
        return all(importlib.util.find_spec(m) is not None for m in ("onnxruntime", "tokenizers"))
    except (ImportError, ValueError):
        return False


def installed() -> bool:
    """The model files are there, complete (their size; the checksum was verified when they were downloaded)."""
    d = model_dir()
    try:
        return all(os.path.getsize(os.path.join(d, name)) == size for name, (_p, _h, size) in FILES.items())
    except OSError:
        return False


def ready() -> bool:
    return runtime_installed() and installed()


def download(progress=None, cancelled=None) -> str:
    """Fetch the model files, verify each one's SHA-256, then move them into place. Returns the model folder.
    progress(fraction) is called while downloading; cancelled() returning True stops it."""
    import downloads
    d = model_dir()
    total = sum(size for _p, _h, size in FILES.values()); before = 0
    for name, (remote, sha, size) in FILES.items():
        target = os.path.join(d, name)
        if not (os.path.exists(target) and os.path.getsize(target) == size):
            report = (lambda got, _all, b=before: progress(min(1.0, (b + got) / total))) if progress else None
            try:
                downloads.fetch(BASE_URL + remote, target, sha, "meaning search model download", report, cancelled)
            except downloads.DownloadError as e:
                raise EmbeddingError(str(e))
        before += size
    return d


def remove() -> None:
    global _model
    import shutil
    with _model_lock: _model = None
    shutil.rmtree(model_dir(), ignore_errors=True)


class _Model:
    def __init__(self, folder: str):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(os.path.join(folder, "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS); self.tok.enable_padding()
        opts = ort.SessionOptions(); opts.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2) - 1))
        opts.log_severity_level = 3
        self.sess = ort.InferenceSession(os.path.join(folder, "model_quantized.onnx"), opts, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}
        self.lock = threading.Lock()                      # one run at a time: the session already uses several cores

    def embed(self, texts: list):
        import numpy as np
        out = []
        for i in range(0, len(texts), BATCH):
            enc = self.tok.encode_batch(texts[i:i + BATCH])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.inputs: feeds["token_type_ids"] = np.zeros_like(ids)
            with self.lock:
                hidden = self.sess.run(None, feeds)[0]
            v = (hidden * mask[..., None]).sum(1) / np.maximum(mask.sum(1, keepdims=True), 1)          # mean of the words
            out.append(v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12))
        return np.vstack(out).astype(np.float32) if out else np.zeros((0, DIM), np.float32)


def _get() -> _Model:
    global _model
    with _model_lock:
        if _model is None:
            if not ready():
                raise EmbeddingError("Search by meaning is not installed (＋ → Documents → Download).")
            _model = _Model(model_dir())
            log.info("meaning model loaded from %s", model_dir())
        return _model


def embed_passages(texts: list):
    """Unit vectors (float32, one row per text) for passages of documents."""
    return _get().embed(["passage: " + t for t in texts])


def embed_query(text: str):
    """The unit vector of a question."""
    return _get().embed(["query: " + text])[0]
