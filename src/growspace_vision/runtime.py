"""Pinned DINOv2 model runtime for one stateless Vision Analysis."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Final, Protocol, cast

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]
from anyio import CancelScope
from numpy.typing import NDArray
from PIL import Image

from growspace_vision.analysis import Analyzer, UnavailableAnalyzer
from growspace_vision.images import DecodedImage

ort.disable_telemetry_events()


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """Identity of model bytes and behavior that may share a Baseline Bucket."""

    model_id: str
    model_version: str
    repository: str
    revision: str
    artifact_path: str
    byte_size: int
    sha256: str
    input_name: str
    output_name: str
    input_width: int
    input_height: int
    mean: tuple[float, float, float]
    standard_deviation: tuple[float, float, float]
    embedding_dimension: int
    runtime_version: str
    execution_provider: str
    intra_op_num_threads: int
    inter_op_num_threads: int


def _load_production_manifest() -> ModelManifest:
    document = cast(
        dict[str, Any],
        json.loads(
            files("growspace_vision")
            .joinpath("model_manifest.json")
            .read_text(encoding="utf-8")
        ),
    )
    artifact = cast(dict[str, Any], document["artifact"])
    model_input = cast(dict[str, Any], document["input"])
    preprocessing = cast(dict[str, Any], document["preprocessing"])
    model_output = cast(dict[str, Any], document["output"])
    runtime = cast(dict[str, Any], document["runtime"])
    resize = cast(list[int], preprocessing["resize"])
    mean = cast(list[float], preprocessing["mean"])
    standard_deviation = cast(list[float], preprocessing["standard_deviation"])
    providers = cast(list[str], runtime["execution_providers"])
    return ModelManifest(
        model_id=str(document["model_id"]),
        model_version=str(document["model_version"]),
        repository=str(artifact["repository"]),
        revision=str(artifact["revision"]),
        artifact_path=str(artifact["path"]),
        byte_size=int(artifact["size_bytes"]),
        sha256=str(artifact["sha256"]),
        input_name=str(model_input["name"]),
        output_name=str(model_output["name"]),
        input_width=resize[0],
        input_height=resize[1],
        mean=(mean[0], mean[1], mean[2]),
        standard_deviation=(
            standard_deviation[0],
            standard_deviation[1],
            standard_deviation[2],
        ),
        embedding_dimension=int(model_output["embedding_dimension"]),
        runtime_version=str(runtime["version"]),
        execution_provider=providers[0],
        intra_op_num_threads=int(runtime["intra_op_num_threads"]),
        inter_op_num_threads=int(runtime["inter_op_num_threads"]),
    )


PRODUCTION_MODEL: Final = _load_production_manifest()


class RuntimeValueInfo(Protocol):
    """ONNX input/output metadata used to reject a different graph."""

    name: str
    shape: Sequence[object]
    type: str


class RuntimeSession(Protocol):
    """Small ONNX Runtime surface needed by the analyzer."""

    def get_inputs(self) -> Sequence[RuntimeValueInfo]: ...

    def get_outputs(self) -> Sequence[RuntimeValueInfo]: ...

    def get_providers(self) -> Sequence[str]: ...

    def run(
        self,
        output_names: Sequence[str],
        input_feed: dict[str, NDArray[np.float32]],
        run_options: ort.RunOptions,
    ) -> Sequence[NDArray[np.float32]]: ...


class ModelIdentityError(ValueError):
    """Verified bytes do not expose the locked DINOv2 runtime contract."""


class DinoV2Analyzer:
    """Ready Analyzer backed by the verified production ONNX session."""

    ready = True

    def __init__(self, manifest: ModelManifest, session: RuntimeSession) -> None:
        self._manifest = manifest
        self.model_id = manifest.model_id
        self.model_version = manifest.model_version
        self.embedding_dimension = manifest.embedding_dimension
        self._session = session

    async def embed(self, image: DecodedImage) -> Sequence[float]:
        """Embed one decoded frame."""

        tensor = await asyncio.to_thread(_preprocess, image, self._manifest)
        run_options = ort.RunOptions()
        inference = asyncio.create_task(
            asyncio.to_thread(
                self._session.run,
                [self._manifest.output_name],
                {self._manifest.input_name: tensor},
                run_options,
            )
        )
        try:
            outputs = await asyncio.shield(inference)
        except asyncio.CancelledError:
            run_options.terminate = True
            # Finish native termination before the caller releases its slot,
            # even while an enclosing AnyIO deadline keeps cancelling awaits.
            with CancelScope(shield=True), suppress(Exception):
                await inference
            raise
        if len(outputs) != 1:
            raise RuntimeError("model returned an unexpected output count")
        hidden_state = np.asarray(outputs[0])
        if (
            hidden_state.ndim != 3
            or hidden_state.shape[0] != 1
            or hidden_state.shape[1] < 1
            or hidden_state.shape[2] != self.embedding_dimension
        ):
            raise RuntimeError("model returned an unexpected output shape")
        cls_token = hidden_state[0, 0, :].astype(np.float64)
        norm = float(np.linalg.norm(cls_token))
        if not np.isfinite(norm) or norm == 0.0:
            raise RuntimeError("model returned an invalid embedding")
        embedding = cls_token / norm
        if not np.isfinite(embedding).all():
            raise RuntimeError("model returned an invalid embedding")
        return cast(list[float], embedding.tolist())


def load_analyzer(
    model_path: Path,
    manifest: ModelManifest,
    create_session: Callable[[str], Any],
) -> Analyzer:
    """Verify model bytes before allowing the runtime to inspect them."""

    try:
        if model_path.stat().st_size != manifest.byte_size:
            return UnavailableAnalyzer()
        digest = hashlib.sha256()
        with model_path.open("rb") as model:
            for block in iter(lambda: model.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != manifest.sha256:
            return UnavailableAnalyzer()
        session = create_session(str(model_path))
        _verify_session_identity(session, manifest)
    except Exception:
        return UnavailableAnalyzer()
    return DinoV2Analyzer(manifest, session)


def load_production_analyzer(model_path: Path) -> Analyzer:
    """Load the bundled production model, or remain fail-closed and unready."""

    return load_analyzer(
        model_path,
        PRODUCTION_MODEL,
        lambda path: _create_cpu_session(path, PRODUCTION_MODEL),
    )


def _create_cpu_session(model_path: str, manifest: ModelManifest) -> RuntimeSession:
    """Construct the measured single-request CPU execution configuration."""

    options = ort.SessionOptions()
    options.intra_op_num_threads = manifest.intra_op_num_threads
    options.inter_op_num_threads = manifest.inter_op_num_threads
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return cast(
        RuntimeSession,
        ort.InferenceSession(
            model_path,
            sess_options=options,
            providers=[manifest.execution_provider],
        ),
    )


def _verify_session_identity(session: RuntimeSession, manifest: ModelManifest) -> None:
    """Require the selected graph's names, tensor contracts, and CPU provider."""

    if list(session.get_providers()) != [manifest.execution_provider]:
        raise ModelIdentityError("model session is not CPU-only")
    inputs = list(session.get_inputs())
    outputs = list(session.get_outputs())
    if len(inputs) != 1 or not _is_expected_input(inputs[0], manifest):
        raise ModelIdentityError("model input identity does not match")
    if len(outputs) != 1 or not _is_expected_output(outputs[0], manifest):
        raise ModelIdentityError("model output identity does not match")


def _is_expected_input(value: RuntimeValueInfo, manifest: ModelManifest) -> bool:
    return (
        value.name == manifest.input_name
        and value.type == "tensor(float)"
        and len(value.shape) == 4
    )


def _is_expected_output(value: RuntimeValueInfo, manifest: ModelManifest) -> bool:
    return (
        value.name == manifest.output_name
        and value.type == "tensor(float)"
        and len(value.shape) == 3
        and value.shape[2] == manifest.embedding_dimension
    )


def _preprocess(image: DecodedImage, manifest: ModelManifest) -> NDArray[np.float32]:
    """Apply model-version 1.0.0 whole-frame preprocessing."""

    resized = Image.fromarray(image.pixels).resize(
        (manifest.input_width, manifest.input_height), Image.Resampling.BICUBIC
    )
    pixels = np.asarray(resized, dtype=np.float32) / np.float32(255.0)
    mean = np.asarray(manifest.mean, dtype=np.float32)
    standard_deviation = np.asarray(manifest.standard_deviation, dtype=np.float32)
    normalized = (pixels - mean) / standard_deviation
    return np.ascontiguousarray(normalized.transpose(2, 0, 1)[None, ...])
