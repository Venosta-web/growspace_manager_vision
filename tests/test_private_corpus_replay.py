"""Privacy and result-shape tests for the private corpus replay tool."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "private_corpus_replay.py"
SPEC = importlib.util.spec_from_file_location("private_corpus_replay", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
replay = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = replay
SPEC.loader.exec_module(replay)


class CorpusDiscoveryTests(unittest.TestCase):
    """The replay refuses a partial or ambiguous private input set."""

    def test_discovers_exactly_one_consecutive_109_frame_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = date(2026, 3, 21)
            for offset in range(109):
                captured = first + timedelta(days=offset)
                (root / f"growcam_sog_{captured:%d.%m.%Y}.jpg").touch()

            frames = replay.discover_corpus(root)

            self.assertEqual(len(frames), 109)
            self.assertEqual(frames[0].captured_on, first)
            self.assertEqual(frames[-1].captured_on, date(2026, 7, 7))
            self.assertEqual(frames[52].segment.name, "occlusion-2")

    def test_refuses_a_partial_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "growcam_sog_21.03.2026.jpg").touch()

            with self.assertRaisesRegex(ValueError, "Expected 109"):
                replay.discover_corpus(root)

    def test_refuses_an_unaccounted_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = date(2026, 3, 21)
            for offset in range(109):
                captured = first + timedelta(days=offset)
                (root / f"growcam_sog_{captured:%d.%m.%Y}.jpg").touch()
            (root / "extra.jpg").touch()

            with self.assertRaisesRegex(ValueError, "outside the expected naming"):
                replay.discover_corpus(root)


class AggregatePrivacyTests(unittest.TestCase):
    """Only aggregate, non-image-bearing results cross the git boundary."""

    def test_aggregate_omits_paths_images_embeddings_and_per_frame_rows(self) -> None:
        rows = [_row(index) for index in range(1, 110)]

        aggregate = replay.build_aggregate(
            rows,
            corpus_manifest_sha256="a" * 64,
            service_info={"service_version": "1.0.0"},
            model={
                "model_id": "model",
                "model_version": "1",
                "embedding_dimension": 384,
            },
            vision_provenance={"repository_commit": "cafe1234"},
            rule_provenance={"repository_commit": "deadbeef"},
            runtime={"host_architecture": "x86_64"},
        )

        encoded = json.dumps(aggregate)
        self.assertNotIn("thumbnail", encoded)
        self.assertNotIn("captured_on", encoded)
        self.assertNotIn('"embedding":', encoded)
        self.assertNotIn('"embedding_values":', encoded)
        self.assertNotIn("/private/source", encoded)
        self.assertTrue(aggregate["privacy"]["aggregate_only"])
        self.assertEqual(aggregate["corpus"]["frame_count"], 109)

    def test_report_uses_the_approved_filmstrip_and_collapses_measurements(
        self,
    ) -> None:
        rows = [_row(index) for index in range(1, 110)]
        aggregate = replay.build_aggregate(
            rows,
            corpus_manifest_sha256="a" * 64,
            service_info={"service_version": "1.0.0"},
            model={
                "model_id": "model",
                "model_version": "1",
                "embedding_dimension": 384,
            },
            vision_provenance={},
            rule_provenance={},
            runtime={},
        )

        html = replay.render_report(rows, aggregate)

        self.assertEqual(html.count("<figure"), 109)
        self.assertIn("<details><summary>Show the measurements</summary>", html)
        self.assertIn("Scene-change monitoring only", html)
        self.assertIn("Plant-health calibration: none in V1", html)
        self.assertIn("zero real health positives", html)
        self.assertIn("Local artefact", html)

    def test_float32_round_trip_matches_the_integration_persistence_boundary(
        self,
    ) -> None:
        self.assertEqual(replay._as_f32((0.1,)), (0.10000000149011612,))


def _row(index: int) -> Any:
    segment = replay.SEGMENTS[min((index - 1) // 13, len(replay.SEGMENTS) - 1)]
    row = replay.ReplayRow(
        index=index,
        captured_on=(date(2026, 3, 20) + timedelta(days=index)).isoformat(),
        segment=segment.name,
        event=segment.event,
        analysis_status="analyzed",
        service_quality_reasons=(),
        quality_signals={
            "mean_luminance": 100.0,
            "clipped_pixel_fraction": 0.1,
            "mean_absolute_gradient": 10.0,
        },
        quality_accepted=True,
        quality_reasons=(),
        quality_reanchored=False,
        comparison_outcome="scored",
        baseline_state="ready",
        samples_collected=30,
        samples_required=30,
        raw_distance=0.05,
        anomaly_score=0.2,
        verdict="normal",
        comparison_confidence=0.8,
        admitted_to_baseline=True,
        latency_ms=250.0,
        thumbnail=f"thumbnails/frame-{index:03d}.jpg",
    )
    return row


if __name__ == "__main__":
    unittest.main()
