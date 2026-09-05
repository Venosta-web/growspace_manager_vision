"""Production DINOv2 runtime behavior at the Analyzer boundary."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import tempfile
import threading
import unittest
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np
from anyio import create_task_group
from numpy.typing import NDArray

from growspace_vision.analysis import Analyzer
from growspace_vision.images import DecodedImage
from growspace_vision.runtime import (
    PRODUCTION_MODEL,
    load_analyzer,
    load_production_analyzer,
)


class FakeValueInfo:
    def __init__(self, name: str, shape: list[object], value_type: str) -> None:
        self.name = name
        self.shape = shape
        self.type = value_type


class CompatibleSession:
    def __init__(self, cls_embedding: NDArray[np.float32] | None = None) -> None:
        self.output_names: list[str] | None = None
        self.input_feed: dict[str, NDArray[np.float32]] | None = None
        self.cls_embedding = cls_embedding

    def get_inputs(self) -> list[FakeValueInfo]:
        return [
            FakeValueInfo(
                "pixel_values",
                ["batch_size", "num_channels", "height", "width"],
                "tensor(float)",
            )
        ]

    def get_outputs(self) -> list[FakeValueInfo]:
        return [
            FakeValueInfo(
                "last_hidden_state",
                ["batch_size", "sequence_length", 384],
                "tensor(float)",
            )
        ]

    def get_providers(self) -> list[str]:
        return ["CPUExecutionProvider"]

    def run(
        self,
        output_names: list[str],
        input_feed: dict[str, NDArray[np.float32]],
        run_options: Any = None,
    ) -> list[NDArray[np.float32]]:
        self.output_names = output_names
        self.input_feed = input_feed
        output = np.zeros((1, 193, 384), dtype=np.float32)
        if self.cls_embedding is None:
            output[0, 0, 0] = 1.0
        else:
            output[0, 0, :] = self.cls_embedding
        output[0, 1, :] = -999.0
        return [output]


class AcceleratedSession(CompatibleSession):
    def get_providers(self) -> list[str]:
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]


class CancellableSession(CompatibleSession):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.stopped = threading.Event()

    def run(
        self,
        output_names: list[str],
        input_feed: dict[str, NDArray[np.float32]],
        run_options: Any = None,
    ) -> list[NDArray[np.float32]]:
        self.started.set()
        while not run_options.terminate:
            self.stopped.wait(0.001)
        # Native inference needs time to observe termination and unwind.
        self.stopped.wait(0.02)
        self.stopped.set()
        raise RuntimeError("inference terminated")


class SessionLoadFailure(Exception):
    pass


def load_fixture_analyzer(session: CompatibleSession) -> Analyzer:
    """Load a deterministic local stand-in through the real identity checks."""

    model_bytes = b"fixture-onnx-model"
    manifest = replace(
        PRODUCTION_MODEL,
        byte_size=len(model_bytes),
        sha256=hashlib.sha256(model_bytes).hexdigest(),
    )
    with tempfile.TemporaryDirectory() as directory:
        model_path = Path(directory) / "model.onnx"
        model_path.write_bytes(model_bytes)
        return load_analyzer(model_path, manifest, lambda path: session)


class ProductionModelStartupTest(unittest.TestCase):
    """A process stays observable but unready until the pinned model is usable."""

    def test_a_missing_model_starts_unready_with_the_production_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            analyzer = load_production_analyzer(Path(directory) / "model_int8.onnx")

        self.assertFalse(analyzer.ready)
        self.assertEqual(analyzer.model_id, "dinov2-vit-s-14-int8-onnx")
        self.assertEqual(analyzer.model_version, "1.0.0")
        self.assertEqual(analyzer.embedding_dimension, 384)

    def test_the_production_identity_names_the_exact_measured_artifact(self) -> None:
        self.assertEqual(PRODUCTION_MODEL.model_id, "dinov2-vit-s-14-int8-onnx")
        self.assertEqual(PRODUCTION_MODEL.model_version, "1.0.0")
        self.assertEqual(PRODUCTION_MODEL.repository, "onnx-community/dinov2-small")
        self.assertEqual(
            PRODUCTION_MODEL.revision,
            "8b1f705a3a7f6f062f6bdd21986c1583d3ef105d",
        )
        self.assertEqual(PRODUCTION_MODEL.artifact_path, "onnx/model_int8.onnx")
        self.assertEqual(PRODUCTION_MODEL.byte_size, 24_446_700)
        self.assertEqual(
            PRODUCTION_MODEL.sha256,
            "dfce54a839b491f395c516350ebb4a78f947e9170a6beac0f2bc5638e0f09d61",
        )
        self.assertEqual(PRODUCTION_MODEL.embedding_dimension, 384)
        self.assertEqual(PRODUCTION_MODEL.runtime_version, "1.29.0")
        self.assertEqual(version("onnxruntime"), PRODUCTION_MODEL.runtime_version)

    def test_same_sized_tampered_bytes_never_reach_onnx_runtime(self) -> None:
        expected = b"expected-model"
        actual = b"tampered-model"
        manifest = replace(
            PRODUCTION_MODEL,
            byte_size=len(expected),
            sha256=hashlib.sha256(expected).hexdigest(),
        )
        session_paths: list[str] = []

        def create_session(path: str) -> Any:
            session_paths.append(path)
            raise AssertionError("unverified bytes reached ONNX Runtime")

        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.onnx"
            model_path.write_bytes(actual)
            analyzer = load_analyzer(model_path, manifest, create_session)

        self.assertFalse(analyzer.ready)
        self.assertEqual(session_paths, [])

    def test_verified_compatible_model_bytes_become_ready(self) -> None:
        analyzer = load_fixture_analyzer(CompatibleSession())

        self.assertTrue(analyzer.ready)
        self.assertEqual(analyzer.model_id, PRODUCTION_MODEL.model_id)
        self.assertEqual(analyzer.model_version, PRODUCTION_MODEL.model_version)
        self.assertEqual(analyzer.embedding_dimension, 384)

    def test_a_session_with_any_non_cpu_provider_stays_unready(self) -> None:
        analyzer = load_fixture_analyzer(AcceleratedSession())

        self.assertFalse(analyzer.ready)

    def test_an_onnx_runtime_load_failure_stays_unready(self) -> None:
        model_bytes = b"fixture-onnx-model"
        manifest = replace(
            PRODUCTION_MODEL,
            byte_size=len(model_bytes),
            sha256=hashlib.sha256(model_bytes).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.onnx"
            model_path.write_bytes(model_bytes)

            analyzer = load_analyzer(
                model_path,
                manifest,
                lambda path: (_ for _ in ()).throw(SessionLoadFailure()),
            )

        self.assertFalse(analyzer.ready)


class ProductionInferenceTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_decoded_rgb_frame_becomes_the_locked_nchw_tensor(self) -> None:
        session = CompatibleSession()
        analyzer = load_fixture_analyzer(session)

        pixels = np.empty((2, 4, 3), dtype=np.uint8)
        pixels[:, :] = (255, 128, 0)
        await analyzer.embed(DecodedImage(pixels=pixels))

        self.assertEqual(session.output_names, ["last_hidden_state"])
        assert session.input_feed is not None
        tensor = session.input_feed["pixel_values"]
        self.assertEqual(tensor.shape, (1, 3, 168, 224))
        self.assertEqual(tensor.dtype, np.float32)
        np.testing.assert_allclose(
            tensor[0, :, 84, 112],
            np.array(
                [
                    (1.0 - 0.485) / 0.229,
                    (128.0 / 255.0 - 0.456) / 0.224,
                    (0.0 - 0.406) / 0.225,
                ],
                dtype=np.float32,
            ),
            rtol=1e-6,
            atol=1e-6,
        )

    async def test_whole_frame_preprocessing_keeps_both_outer_edges(self) -> None:
        session = CompatibleSession()
        analyzer = load_fixture_analyzer(session)
        pixels = np.full((2, 8, 3), (0, 255, 0), dtype=np.uint8)
        pixels[:, :2] = (255, 0, 0)
        pixels[:, 6:] = (0, 0, 255)

        await analyzer.embed(DecodedImage(pixels=pixels))

        assert session.input_feed is not None
        tensor = session.input_feed["pixel_values"]
        red = np.array(
            [(1.0 - 0.485) / 0.229, -0.456 / 0.224, -0.406 / 0.225],
            dtype=np.float32,
        )
        blue = np.array(
            [-0.485 / 0.229, -0.456 / 0.224, (1.0 - 0.406) / 0.225],
            dtype=np.float32,
        )
        np.testing.assert_allclose(tensor[0, :, 84, 0], red, rtol=1e-6, atol=1e-6)
        np.testing.assert_allclose(tensor[0, :, 84, -1], blue, rtol=1e-6, atol=1e-6)

    async def test_inference_returns_only_the_unit_normalized_cls_token(self) -> None:
        cls_embedding = np.arange(1, 385, dtype=np.float32)
        analyzer = load_fixture_analyzer(CompatibleSession(cls_embedding))

        embedding = await analyzer.embed(
            DecodedImage(pixels=np.full((8, 8, 3), 127, dtype=np.uint8))
        )

        denominator = math.sqrt(384 * 385 * 769 / 6)
        self.assertEqual(len(embedding), 384)
        self.assertAlmostEqual(math.fsum(value * value for value in embedding), 1.0)
        self.assertAlmostEqual(embedding[0], 1.0 / denominator)
        self.assertAlmostEqual(embedding[-1], 384.0 / denominator)

    async def test_a_cancelled_deadline_terminates_the_cpu_inference(self) -> None:
        session = CancellableSession()
        analyzer = load_fixture_analyzer(session)
        task = asyncio.create_task(
            analyzer.embed(DecodedImage(pixels=np.full((8, 8, 3), 127, dtype=np.uint8)))
        )
        started = await asyncio.to_thread(session.started.wait, 1.0)
        self.assertTrue(started)

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        self.assertTrue(session.stopped.wait(1.0))

    async def test_cancel_scope_waits_for_native_inference_to_stop(self) -> None:
        session = CancellableSession()
        analyzer = load_fixture_analyzer(session)

        async with create_task_group() as tasks:
            tasks.start_soon(
                analyzer.embed,
                DecodedImage(pixels=np.full((8, 8, 3), 127, dtype=np.uint8)),
            )
            self.assertTrue(await asyncio.to_thread(session.started.wait, 1.0))
            tasks.cancel_scope.cancel()

        # The service may release its inference slot only after native work ends.
        self.assertTrue(session.stopped.is_set())


@unittest.skipUnless(
    os.environ.get("GROWSPACE_VISION_TEST_MODEL_PATH"),
    "the verified production artifact was not supplied locally",
)
class ProductionArtifactTest(unittest.IsolatedAsyncioTestCase):
    """Exercise the exact pinned bytes without granting the test network access."""

    async def test_the_pinned_artifact_loads_and_returns_a_unit_embedding(self) -> None:
        model_path = Path(os.environ["GROWSPACE_VISION_TEST_MODEL_PATH"])
        analyzer = load_production_analyzer(model_path)

        self.assertTrue(analyzer.ready)
        pixels = np.indices((64, 96)).sum(axis=0).astype(np.uint8)
        rgb = np.stack((pixels, np.flip(pixels, axis=1), pixels // 2), axis=2)
        embedding = await analyzer.embed(DecodedImage(pixels=rgb))

        fixture = Path(__file__).parent / "fixtures" / "dinov2-golden-embedding.json"
        expected = json.loads(fixture.read_text(encoding="utf-8"))

        self.assertEqual(len(embedding), 384)
        self.assertAlmostEqual(math.fsum(value * value for value in embedding), 1.0)
        np.testing.assert_allclose(embedding, expected, rtol=1e-5, atol=1e-7)


if __name__ == "__main__":
    unittest.main()
