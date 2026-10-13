"""Sealed provider keys (format v1): only the holder of the runner's private key can open them, and a sealed value cannot
be moved to another model row, another key id, or altered."""

import base64
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from monitor.cloud import seal

ROOT = Path(__file__).resolve().parent.parent
MODEL = str(uuid.UUID("11111111-2222-4333-8444-555555555555"))
PROVIDER_KEY = "gsk_" + "p" * 40


def test_a_sealed_key_opens_only_with_the_private_key_and_the_same_row_and_key_id():
    priv, pub = seal.generate_keypair()
    box = seal.seal(PROVIDER_KEY, MODEL, 1, pub)
    assert set(box) == {"key_id", "ephemeral", "nonce", "ciphertext"} and box["key_id"] == 1
    assert len(base64.b64decode(box["ephemeral"])) == 32 and len(base64.b64decode(box["nonce"])) == 12
    assert PROVIDER_KEY not in json.dumps(box) and PROVIDER_KEY.encode() not in base64.b64decode(box["ciphertext"])
    assert seal.open_sealed(priv, MODEL, box) == PROVIDER_KEY


def test_every_seal_is_different_even_for_the_same_key():
    _, pub = seal.generate_keypair()
    a, b = seal.seal(PROVIDER_KEY, MODEL, 1, pub), seal.seal(PROVIDER_KEY, MODEL, 1, pub)
    assert a["ciphertext"] != b["ciphertext"] and a["ephemeral"] != b["ephemeral"] and a["nonce"] != b["nonce"]


def test_a_sealed_key_cannot_be_moved_altered_or_opened_by_anyone_else():
    priv, pub = seal.generate_keypair()
    other_priv, _ = seal.generate_keypair()
    box = seal.seal(PROVIDER_KEY, MODEL, 1, pub)
    with pytest.raises(seal.SealError):
        seal.open_sealed(priv, str(uuid.uuid4()), box)  # another model row
    with pytest.raises(seal.SealError):
        seal.open_sealed(priv, MODEL, {**box, "key_id": 2})  # another key id
    with pytest.raises(seal.SealError):
        seal.open_sealed(other_priv, MODEL, box)  # another private key
    raw = bytearray(base64.b64decode(box["ciphertext"]))
    raw[0] ^= 1
    with pytest.raises(seal.SealError):
        seal.open_sealed(priv, MODEL, {**box, "ciphertext": base64.b64encode(bytes(raw)).decode()})  # tampered
    for field in ("ephemeral", "nonce", "ciphertext"):
        with pytest.raises(seal.SealError):
            seal.open_sealed(priv, MODEL, {**box, field: base64.b64encode(b"short").decode()})
        with pytest.raises(seal.SealError):
            seal.open_sealed(priv, MODEL, {**box, field: "!!!not base64!!!"})
    with pytest.raises(seal.SealError):
        seal.open_sealed(priv, MODEL, {"key_id": 1})  # missing fields


def test_errors_never_carry_the_key_or_the_private_key():
    priv, pub = seal.generate_keypair()
    box = seal.seal(PROVIDER_KEY, MODEL, 1, pub)
    with pytest.raises(seal.SealError) as e:
        seal.open_sealed(base64.b64encode(b"\x01" * 32).decode(), MODEL, box)
    assert PROVIDER_KEY not in str(e.value) and priv not in str(e.value)


def test_bad_inputs_are_refused_when_sealing():
    _, pub = seal.generate_keypair()
    for bad_key in ("", "x" * 5000, None):
        with pytest.raises(seal.SealError):
            seal.seal(bad_key, MODEL, 1, pub)  # type: ignore[arg-type]
    with pytest.raises(seal.SealError):
        seal.seal(PROVIDER_KEY, "not-a-uuid", 1, pub)
    with pytest.raises(seal.SealError):
        seal.seal(PROVIDER_KEY, MODEL, 0, pub)
    with pytest.raises(seal.SealError):
        seal.seal(PROVIDER_KEY, MODEL, 1, "AAAA")


def test_the_committed_vectors_made_by_node_open_in_python():
    """tests/fixtures/seal_v1.json was written by frontend/scripts/make-seal-fixture.mjs (Node's crypto)."""
    fx = json.loads((ROOT / "tests" / "fixtures" / "seal_v1.json").read_text(encoding="utf-8"))
    assert len(fx["vectors"]) >= 3
    for v in fx["vectors"]:
        assert seal.open_sealed(fx["private_key"], v["model_id"], v["box"]) == v["plaintext"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_fresh_node_seal_opens_in_python_and_binds_the_row():
    priv, pub = seal.generate_keypair()
    code = (
        "import { sealSecret } from './lib/connect/seal.ts';"
        f"const box = sealSecret({json.dumps(PROVIDER_KEY)}, {json.dumps(MODEL)}, 3, {json.dumps(pub)});"
        "console.log(JSON.stringify(box));"
    )
    out = subprocess.run(
        ["node", "--import", "tsx", "--input-type=module", "-e", code],
        cwd=ROOT / "frontend", capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr[-800:]
    box = json.loads(out.stdout.strip().splitlines()[-1])
    assert box["key_id"] == 3 and seal.open_sealed(priv, MODEL, box) == PROVIDER_KEY
    with pytest.raises(seal.SealError):
        seal.open_sealed(priv, str(uuid.uuid4()), box)
