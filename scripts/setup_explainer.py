"""Fetch pinned public Qwen model files; never sends user inputs."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "Qwen/Qwen2.5-0.5B-Instruct"
REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
WEIGHT_SHA256 = "fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe"
FILES = ("config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json",
         "merges.txt", "vocab.json", "model.safetensors")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main():
    directory = ROOT / "models" / "qwen2.5-0.5b-instruct"
    directory.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = directory / name
        if name == "model.safetensors" and target.exists() and sha256(target) == WEIGHT_SHA256:
            print("Verified cached model weights.", flush=True)
            continue
        temporary = directory / (name + ".download")
        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}?download=true"
        try:
            with urllib.request.urlopen(url, timeout=30) as response, temporary.open("wb") as output:
                expected_size = int(response.headers.get("Content-Length", "0"))
                received = 0
                while block := response.read(1024 * 1024):
                    output.write(block)
                    received += len(block)
                    if name == "model.safetensors" and received % (128 * 1024 * 1024) == 0:
                        print(f"Weights: {received // (1024 * 1024)} MiB downloaded.", flush=True)
            if expected_size and temporary.stat().st_size != expected_size:
                raise RuntimeError(f"Incomplete download: {name}")
            if name == "model.safetensors" and sha256(temporary) != WEIGHT_SHA256:
                raise RuntimeError("Downloaded weights failed the pinned checksum.")
            temporary.replace(target)
            print(f"Downloaded {name}.", flush=True)
        finally:
            temporary.unlink(missing_ok=True)
    manifest = {"model": REPO, "revision": REVISION, "source": f"https://huggingface.co/{REPO}",
                "license": "Apache-2.0", "purpose": "Explain supplied research notes; no stress classification",
                "files": {name: {"bytes": (directory / name).stat().st_size,
                                 "sha256": sha256(directory / name)} for name in FILES}}
    (ROOT / "models" / "explainer_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"model": REPO, "revision": REVISION,
                      "bytes": sum(f["bytes"] for f in manifest["files"].values())}))


if __name__ == "__main__":
    main()
