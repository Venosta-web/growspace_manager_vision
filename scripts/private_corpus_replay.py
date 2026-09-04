#!/usr/bin/env python3
"""Replay the private corpus through Vision and Home Assistant production rules.

The source images, embeddings, thumbnails, and per-frame ledger stay in the ignored
output directory.  ``aggregate.json`` is deliberately shaped so its contents can be
reviewed and committed without publishing image-bearing or per-frame evidence.
"""

# The report template is intentionally kept as readable HTML rather than wrapped into
# dozens of fragments at Python's line-length boundary.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import mimetypes
import platform
import re
import statistics
import struct
import subprocess
import sys
import time as clock
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from html import escape
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

EXPECTED_FRAME_COUNT = 109
MODEL_SCHEMA_VERSION = 1
SCORING_POLICY_VERSION = 1
DEFAULT_CAMERA_ID = "private-corpus-camera"
DEFAULT_GROWSPACE_ID = "private-corpus-growspace"
DEFAULT_GROW_RUN_ID = "private-corpus-grow-run"
DEFAULT_FRAMING_EPOCH_ID = "private-corpus-framing-epoch"
_DATE_RE = re.compile(r"^growcam_sog_(\d{2})\.(\d{2})\.(\d{4})\.jpg$", re.I)


@dataclass(frozen=True, slots=True)
class Segment:
    """Published, human-reviewed scene segment from the earlier corpus study."""

    name: str
    start: date
    end: date
    event: str | None


SEGMENTS = (
    Segment("framing-1 veg", date(2026, 3, 21), date(2026, 4, 12), None),
    Segment("occlusion-1", date(2026, 4, 13), date(2026, 4, 21), "occlusion"),
    Segment("framing-2", date(2026, 4, 22), date(2026, 4, 26), "reframe"),
    Segment("framing-3", date(2026, 4, 27), date(2026, 5, 3), "reframe"),
    Segment("occlusion-2", date(2026, 5, 4), date(2026, 5, 15), "occlusion"),
    Segment("reframe day", date(2026, 5, 16), date(2026, 5, 16), "reframe"),
    Segment("framing-4 stable", date(2026, 5, 17), date(2026, 6, 20), None),
    Segment("post-harvest", date(2026, 6, 21), date(2026, 6, 24), "harvest"),
    Segment("lights-off", date(2026, 6, 25), date(2026, 7, 7), "lights-off"),
)


@dataclass(frozen=True, slots=True)
class CorpusFrame:
    """One source image discovered without copying it into repository state."""

    index: int
    captured_on: date
    path: Path
    segment: Segment


@dataclass(frozen=True, slots=True)
class Analysis:
    """The evidence needed after one production Vision HTTP response."""

    status: str
    quality_signals: Mapping[str, float]
    quality_reasons: tuple[str, ...]
    embedding: tuple[float, ...] | None
    latency_ms: float


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Home Assistant's two rule decisions for one Vision Analysis."""

    quality_accepted: bool
    quality_reasons: tuple[str, ...]
    quality_reanchored: bool
    comparison_outcome: str | None
    baseline_state: str | None
    samples_collected: int | None
    samples_required: int | None
    raw_distance: float | None
    anomaly_score: float | None
    verdict: str | None
    comparison_confidence: float | None
    admitted_to_baseline: bool


@dataclass(frozen=True, slots=True)
class ReplayRow:
    """Local-only per-frame ledger entry.  It intentionally carries no embedding."""

    index: int
    captured_on: str
    segment: str
    event: str | None
    analysis_status: str
    service_quality_reasons: tuple[str, ...]
    quality_signals: Mapping[str, float]
    quality_accepted: bool
    quality_reasons: tuple[str, ...]
    quality_reanchored: bool
    comparison_outcome: str | None
    baseline_state: str | None
    samples_collected: int | None
    samples_required: int | None
    raw_distance: float | None
    anomaly_score: float | None
    verdict: str | None
    comparison_confidence: float | None
    admitted_to_baseline: bool
    latency_ms: float
    thumbnail: str


class RuleRunner(Protocol):
    """Minimal seam implemented by the production Home Assistant adapter."""

    provenance: Mapping[str, Any]

    def evaluate(
        self, frame: CorpusFrame, analysis: Analysis, model: Mapping[str, Any]
    ) -> RuleResult: ...


def discover_corpus(corpus_dir: Path) -> list[CorpusFrame]:
    """Return exactly the expected consecutive private captures in run order."""
    if not corpus_dir.is_dir():
        raise ValueError(f"Corpus directory does not exist: {corpus_dir}")
    discovered: list[tuple[date, Path]] = []
    unexpected_images: list[str] = []
    for path in corpus_dir.iterdir():
        if not path.is_file():
            continue
        match = _DATE_RE.fullmatch(path.name)
        if match:
            day, month, year = (int(value) for value in match.groups())
            discovered.append((date(year, month, day), path))
        elif path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            unexpected_images.append(path.name)
    discovered.sort()
    if unexpected_images:
        raise ValueError(
            "Corpus contains image files outside the expected naming contract: "
            + ", ".join(sorted(unexpected_images))
        )
    if len(discovered) != EXPECTED_FRAME_COUNT:
        raise ValueError(
            f"Expected {EXPECTED_FRAME_COUNT} corpus frames, found {len(discovered)}"
        )
    dates = [captured_on for captured_on, _ in discovered]
    if len(set(dates)) != len(dates):
        raise ValueError("Corpus contains duplicate capture dates")
    expected_days = (dates[-1] - dates[0]).days + 1
    if expected_days != len(dates):
        raise ValueError("Corpus is not one consecutive daily capture sequence")
    frames: list[CorpusFrame] = []
    for index, (captured_on, path) in enumerate(discovered, start=1):
        segment = next(
            (
                candidate
                for candidate in SEGMENTS
                if candidate.start <= captured_on <= candidate.end
            ),
            None,
        )
        if segment is None:
            raise ValueError(
                f"Capture date falls outside the published segments: {path}"
            )
        frames.append(CorpusFrame(index, captured_on, path, segment))
    return frames


class VisionClient:
    """Small no-proxy client for the production V1 HTTP boundary."""

    def __init__(self, base_url: str, token: str, timeout_seconds: float) -> None:
        if not token or "\n" in token or "\r" in token:
            raise ValueError("Vision token must be one non-empty line")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._opener = build_opener(ProxyHandler({}))
        self.container_name: str | None = None

    def negotiate(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Read the production service and select its one loaded model."""
        health = self._get_json("/health", authenticated=False)
        if health.get("status") != "ready":
            raise RuntimeError(f"Vision service is not ready: {health.get('status')!r}")
        info = self._get_json("/info", authenticated=True)
        models = self._get_json("/models?schema_version=1", authenticated=True)
        loaded = [
            model
            for model in models.get("models", [])
            if model.get("state") == "loaded"
        ]
        if len(loaded) != 1:
            raise RuntimeError(f"Expected one loaded Vision model, found {len(loaded)}")
        model = cast(dict[str, Any], loaded[0])
        if model.get("embedding_dimension") != 384:
            raise RuntimeError(
                "Loaded model does not expose the V1 embedding dimension"
            )
        return info, model

    def analyze(self, frame: CorpusFrame, model: Mapping[str, Any]) -> Analysis:
        """Send one frame through POST /analyze and validate its closed essentials."""
        captured_at = (
            datetime.combine(frame.captured_on, time(12), tzinfo=UTC)
            .isoformat()
            .replace("+00:00", "Z")
        )
        metadata = json.dumps(
            {
                "schema_version": MODEL_SCHEMA_VERSION,
                "camera_id": DEFAULT_CAMERA_ID,
                "growspace_id": DEFAULT_GROWSPACE_ID,
                "captured_at": captured_at,
                # The historical corpus has no trustworthy light-state metadata.
                "light_state": "unknown",
                "model_id": model["model_id"],
                "model_version": model["model_version"],
            },
            separators=(",", ":"),
        ).encode()
        body, content_type = _multipart_body(frame.path, metadata)
        request = Request(
            f"{self._base_url}/analyze",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": content_type,
                "Content-Length": str(len(body)),
                "Accept": "application/json",
            },
        )
        started = clock.perf_counter_ns()
        response = self._request_json(request)
        latency_ms = (clock.perf_counter_ns() - started) / 1_000_000
        status = response.get("status")
        if status not in {"analyzed", "rejected"}:
            raise RuntimeError(f"Unexpected Vision Analysis status: {status!r}")
        quality = _mapping(response.get("quality"), "quality")
        signals_raw = _mapping(quality.get("signals"), "quality.signals")
        signals = {
            name: _finite_number(signals_raw.get(name), f"quality.signals.{name}")
            for name in (
                "mean_luminance",
                "clipped_pixel_fraction",
                "mean_absolute_gradient",
            )
        }
        reasons = tuple(_string_list(quality.get("reasons"), "quality.reasons"))
        embedding: tuple[float, ...] | None = None
        if status == "analyzed":
            embedding_raw = _mapping(response.get("embedding"), "embedding")
            values = embedding_raw.get("values")
            if not isinstance(values, list):
                raise RuntimeError("Vision response embedding.values is not an array")
            embedding = tuple(
                _finite_number(value, "embedding.values[]") for value in values
            )
            if (
                embedding_raw.get("dimension") != len(embedding)
                or len(embedding) != 384
            ):
                raise RuntimeError(
                    "Vision response carries an invalid embedding dimension"
                )
            identity = _mapping(response.get("model"), "model")
            if any(
                identity.get(key) != model.get(key)
                for key in ("model_id", "model_version")
            ):
                raise RuntimeError(
                    "Vision response changed the negotiated model identity"
                )
        elif response.get("embedding") is not None:
            raise RuntimeError(
                "Rejected Vision response unexpectedly carries an embedding"
            )
        return Analysis(status, signals, reasons, embedding, latency_ms)

    def _get_json(self, path: str, *, authenticated: bool) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._token}"
        return self._request_json(Request(f"{self._base_url}{path}", headers=headers))

    def _request_json(self, request: Request) -> dict[str, Any]:
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                if response.headers.get_content_type() != "application/json":
                    raise RuntimeError("Vision service returned a non-JSON response")
                payload = json.load(response)
        except HTTPError as error:
            message = error.read().decode(errors="replace")[:500]
            raise RuntimeError(
                f"Vision service returned HTTP {error.code}: {message}"
            ) from error
        except URLError as error:
            raise RuntimeError(
                f"Cannot reach Vision service: {error.reason}"
            ) from error
        if not isinstance(payload, dict):
            raise RuntimeError("Vision service returned a non-object JSON body")
        return cast(dict[str, Any], payload)


class HomeAssistantRules:
    """Adapter that executes the integration's production quality/comparison classes."""

    def __init__(self, backend_root: Path) -> None:
        root = backend_root.resolve()
        package = root / "custom_components" / "growspace_manager"
        quality_path = package / "domain" / "vision_quality.py"
        comparison_path = package / "domain" / "visual_comparison.py"
        models_path = package / "models" / "vision_evidence.py"
        for path in (quality_path, comparison_path, models_path):
            if not path.is_file():
                raise ValueError(
                    f"Home Assistant production rule source is missing: {path}"
                )
        sys.path.insert(0, str(root))
        quality = importlib.import_module(
            "custom_components.growspace_manager.domain.vision_quality"
        )
        comparison = importlib.import_module(
            "custom_components.growspace_manager.domain.visual_comparison"
        )
        models = importlib.import_module(
            "custom_components.growspace_manager.models.vision_evidence"
        )
        self._assert_loaded_from(quality, quality_path)
        self._assert_loaded_from(comparison, comparison_path)
        self._assert_loaded_from(models, models_path)
        self._quality_module = quality
        self._comparison_module = comparison
        self._models_module = models
        self._quality_history = quality.QualityHistory()
        self._comparison_engine = comparison.VisualComparisonEngine(
            bucket_id_factory=lambda: "private-corpus-baseline"
        )
        self._baseline: Any = None
        self.provenance: Mapping[str, Any] = {
            "repository_commit": _git_value(root, "rev-parse", "HEAD"),
            "repository_dirty": bool(_git_value(root, "status", "--porcelain")),
            "rule_source_sha256": {
                str(path.relative_to(root)): _sha256_file(path)
                for path in (quality_path, comparison_path, models_path)
            },
            "scoring_policy_version": SCORING_POLICY_VERSION,
        }

    @staticmethod
    def _assert_loaded_from(module: ModuleType, expected: Path) -> None:
        actual = Path(cast(str, module.__file__)).resolve()
        if actual != expected.resolve():
            raise RuntimeError(
                f"Loaded {module.__name__} from {actual}, expected {expected}"
            )

    def evaluate(
        self, frame: CorpusFrame, analysis: Analysis, model: Mapping[str, Any]
    ) -> RuleResult:
        """Apply the same service-result -> quality -> comparison order as the scheduler."""
        signals = self._quality_module.QualitySignals(
            mean_luminance=analysis.quality_signals["mean_luminance"],
            clipped_pixel_fraction=analysis.quality_signals["clipped_pixel_fraction"],
            mean_absolute_gradient=analysis.quality_signals["mean_absolute_gradient"],
        )
        quality = self._quality_history.evaluate(
            signals,
            service_accepted=analysis.status == "analyzed",
            service_reasons=analysis.quality_reasons,
        )
        self._quality_history = quality.next_history
        empty = RuleResult(
            quality.accepted,
            tuple(str(reason) for reason in quality.reasons),
            quality.reanchored,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )
        if not quality.accepted:
            return empty
        if analysis.embedding is None:
            raise RuntimeError(
                "Home Assistant accepted a response without an embedding"
            )
        captured_at = datetime.combine(frame.captured_on, time(12), tzinfo=UTC)
        key = self._comparison_module.BaselineKey(
            growspace_id=DEFAULT_GROWSPACE_ID,
            camera_id=DEFAULT_CAMERA_ID,
            light_window=self._models_module.LightWindow.MID,
            grow_run_id=DEFAULT_GROW_RUN_ID,
            model_id=model["model_id"],
            model_version=model["model_version"],
            framing_epoch_id=DEFAULT_FRAMING_EPOCH_ID,
            scoring_policy_version=SCORING_POLICY_VERSION,
        )
        decision = self._comparison_engine.evaluate(
            key,
            self._comparison_module.VisualEmbeddingCapture(
                capture_id=f"private-frame-{frame.index:03d}",
                captured_at=captured_at,
                values=_as_f32(analysis.embedding),
                trigger_source=self._models_module.CaptureTrigger.SCHEDULED,
                quality_accepted=True,
            ),
            self._baseline,
        )
        self._baseline = decision.baseline
        comparison = decision.comparison
        if comparison is None:
            raise RuntimeError("Accepted capture produced no Visual Comparison Result")
        return RuleResult(
            quality.accepted,
            tuple(str(reason) for reason in quality.reasons),
            quality.reanchored,
            _enum_value(comparison.outcome),
            _enum_value(comparison.baseline_state),
            comparison.samples_collected,
            comparison.samples_required,
            comparison.raw_distance,
            comparison.anomaly_score,
            _enum_value(comparison.verdict),
            comparison.comparison_confidence,
            decision.admitted,
        )


def replay(
    frames: Sequence[CorpusFrame],
    client: VisionClient,
    rules: RuleRunner,
    output_dir: Path,
) -> tuple[list[ReplayRow], dict[str, Any]]:
    """Run the complete local-only replay and materialize its private report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    info, model = client.negotiate()
    rows: list[ReplayRow] = []
    manifest_hasher = hashlib.sha256()
    thumbnails = output_dir / "thumbnails"
    thumbnails.mkdir(exist_ok=True)
    for frame in frames:
        frame_digest = _sha256_file(frame.path)
        manifest_hasher.update(f"{frame.index:03d} {frame_digest}\n".encode())
        analysis = client.analyze(frame, model)
        result = rules.evaluate(frame, analysis, model)
        thumbnail = thumbnails / f"frame-{frame.index:03d}.jpg"
        _make_thumbnail(frame.path, thumbnail)
        rows.append(
            ReplayRow(
                frame.index,
                frame.captured_on.isoformat(),
                frame.segment.name,
                frame.segment.event,
                analysis.status,
                analysis.quality_reasons,
                analysis.quality_signals,
                result.quality_accepted,
                result.quality_reasons,
                result.quality_reanchored,
                result.comparison_outcome,
                result.baseline_state,
                result.samples_collected,
                result.samples_required,
                result.raw_distance,
                result.anomaly_score,
                result.verdict,
                result.comparison_confidence,
                result.admitted_to_baseline,
                analysis.latency_ms,
                f"thumbnails/{thumbnail.name}",
            )
        )
        print(
            f"[{frame.index:03d}/{len(frames)}] {frame.captured_on} "
            f"analysis={analysis.status} quality={'accepted' if result.quality_accepted else 'rejected'} "
            f"comparison={result.verdict or result.comparison_outcome or 'unavailable'} "
            f"{analysis.latency_ms:.1f}ms",
            flush=True,
        )
    runtime = _container_runtime(getattr(client, "container_name", None))
    aggregate = build_aggregate(
        rows,
        corpus_manifest_sha256=manifest_hasher.hexdigest(),
        service_info=info,
        model=model,
        vision_provenance=_vision_source_provenance(),
        rule_provenance=rules.provenance,
        runtime=runtime,
    )
    (output_dir / "ledger.json").write_text(
        json.dumps([asdict(row) for row in rows], indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "aggregate.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "report.html").write_text(
        render_report(rows, aggregate), encoding="utf-8"
    )
    return rows, aggregate


def build_aggregate(
    rows: Sequence[ReplayRow],
    *,
    corpus_manifest_sha256: str,
    service_info: Mapping[str, Any],
    model: Mapping[str, Any],
    vision_provenance: Mapping[str, Any],
    rule_provenance: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the only publishable artifact: aggregate, non-image-bearing facts."""
    latencies = [row.latency_ms for row in rows]
    service_reasons = Counter(
        reason for row in rows for reason in row.service_quality_reasons
    )
    ha_reasons = Counter(reason for row in rows for reason in row.quality_reasons)
    verdicts = Counter(
        row.verdict or row.comparison_outcome or "unavailable" for row in rows
    )
    baseline_states = Counter(row.baseline_state or "unavailable" for row in rows)
    raw_distances = [row.raw_distance for row in rows if row.raw_distance is not None]
    anomaly_scores = [
        row.anomaly_score for row in rows if row.anomaly_score is not None
    ]
    by_segment: dict[str, Any] = {}
    for segment in SEGMENTS:
        segment_rows = [row for row in rows if row.segment == segment.name]
        distances = [
            row.raw_distance for row in segment_rows if row.raw_distance is not None
        ]
        by_segment[segment.name] = {
            "frames": len(segment_rows),
            "event": segment.event,
            "quality_rejected": sum(not row.quality_accepted for row in segment_rows),
            "verdicts": dict(
                sorted(
                    Counter(
                        row.verdict or row.comparison_outcome or "unavailable"
                        for row in segment_rows
                    ).items()
                )
            ),
            "raw_distance": _distribution(distances),
        }
    discrepancies = _discrepancies(rows)
    return {
        "schema_version": 1,
        "privacy": {
            "aggregate_only": True,
            "contains_source_paths": False,
            "contains_images": False,
            "contains_embeddings": False,
            "contains_per_frame_results": False,
        },
        "corpus": {
            "frame_count": len(rows),
            "consecutive_daily_frames": len(rows) == EXPECTED_FRAME_COUNT,
            "ordered_manifest_sha256": corpus_manifest_sha256,
            "health_positive_count": 0,
            "light_window_metadata_available": False,
            "framing_epoch_actions_available": False,
        },
        "pipeline": {
            "service_version": service_info.get("service_version"),
            "schema_version": MODEL_SCHEMA_VERSION,
            "model_id": model.get("model_id"),
            "model_version": model.get("model_version"),
            "embedding_dimension": model.get("embedding_dimension"),
            "vision_source": dict(vision_provenance),
            "home_assistant_rules": dict(rule_provenance),
            "runtime": dict(runtime),
        },
        "results": {
            "analysis_status": dict(
                sorted(Counter(row.analysis_status for row in rows).items())
            ),
            "service_quality_reasons": dict(sorted(service_reasons.items())),
            "home_assistant_quality": {
                "accepted": sum(row.quality_accepted for row in rows),
                "rejected": sum(not row.quality_accepted for row in rows),
                "reanchored": sum(row.quality_reanchored for row in rows),
                "reasons": dict(sorted(ha_reasons.items())),
            },
            "comparison_verdicts": dict(sorted(verdicts.items())),
            "baseline_states": dict(sorted(baseline_states.items())),
            "quality_signals": {
                name: _distribution([row.quality_signals[name] for row in rows])
                for name in (
                    "mean_luminance",
                    "clipped_pixel_fraction",
                    "mean_absolute_gradient",
                )
            },
            "raw_distance": _distribution(raw_distances),
            "anomaly_score": _distribution(anomaly_scores),
            "latency_ms": _distribution(latencies),
            "latency_ms_by_analysis_status": {
                status: _distribution(
                    [row.latency_ms for row in rows if row.analysis_status == status]
                )
                for status in sorted({row.analysis_status for row in rows})
            },
            "by_segment": by_segment,
        },
        "discrepancies": discrepancies,
        "limitations": [
            "The corpus has zero real plant-health positives, so only specificity is measurable.",
            "Historical light-window metadata is unavailable; replay uses one synthetic mid-light bucket and light_state=unknown.",
            "Historical manual Framing Epoch restart actions are unavailable; replay uses one uninterrupted epoch.",
            "Physical arm64 latency and memory remain unmeasured.",
        ],
    }


def _discrepancies(rows: Sequence[ReplayRow]) -> list[dict[str, Any]]:
    """Compare production replay outcomes with already-published corpus facts."""
    discrepancies: list[dict[str, Any]] = []
    service_rejected = [row for row in rows if row.analysis_status == "rejected"]
    if len(service_rejected) != 13:
        discrepancies.append(
            {
                "code": "absolute_quality_rejection_count_changed",
                "severity": "contradictory_evidence",
                "observed": len(service_rejected),
                "expected": 13,
                "affected_frames": abs(len(service_rejected) - 13),
                "summary": "Production absolute-floor rejections differ from the locked 13 dark-frame results.",
            }
        )
    all_quality_rejected = [row for row in rows if not row.quality_accepted]
    if len(all_quality_rejected) != 14:
        discrepancies.append(
            {
                "code": "combined_quality_rejection_count_changed",
                "severity": "contradictory_evidence",
                "observed": len(all_quality_rejected),
                "expected": 14,
                "affected_frames": abs(len(all_quality_rejected) - 14),
                "summary": "The combined Vision and Home Assistant gate differs from the locked 14-of-109 result.",
            }
        )
    stable_alerts = [
        row
        for row in rows
        if row.segment == "framing-4 stable"
        and row.verdict in {"uncertain", "material_scene_change"}
    ]
    if stable_alerts:
        discrepancies.append(
            {
                "code": "stable_framing_non_normal",
                "severity": "review",
                "observed": len(stable_alerts),
                "expected": 0,
                "affected_frames": len(stable_alerts),
                "summary": "Known stable-framing captures produced non-normal comparison verdicts.",
            }
        )
    known_event_normals = [row for row in rows if row.event and row.verdict == "normal"]
    if known_event_normals:
        discrepancies.append(
            {
                "code": "known_scene_event_scored_normal",
                "severity": "review",
                "observed": len(known_event_normals),
                "expected": 0,
                "affected_frames": len(known_event_normals),
                "summary": "Human-reviewed scene-event captures were scored normal under the uninterrupted production baseline.",
            }
        )
    stale = [row for row in rows if row.baseline_state == "stale"]
    if stale:
        discrepancies.append(
            {
                "code": "baseline_staled_after_non_admission_streak",
                "severity": "operational",
                "observed": len(stale),
                "expected": 0,
                "affected_frames": len(stale),
                "summary": "Scene-change non-admissions left the rolling bucket stale, so later accepted frames could only be monitored.",
            }
        )
    if not any(row.baseline_state == "ready" for row in rows):
        discrepancies.append(
            {
                "code": "baseline_never_ready",
                "severity": "operational",
                "observed": 0,
                "expected": 30,
                "affected_frames": len(rows),
                "summary": "The uninterrupted replay never produced a ready Baseline Bucket.",
            }
        )
    return discrepancies


def render_report(rows: Sequence[ReplayRow], aggregate: Mapping[str, Any]) -> str:
    """Render the approved C filmstrip with every measurement behind disclosure."""
    results = cast(Mapping[str, Any], aggregate["results"])
    quality = cast(Mapping[str, Any], results["home_assistant_quality"])
    verdicts = cast(Mapping[str, int], results["comparison_verdicts"])
    discrepancies = cast(Sequence[Mapping[str, Any]], aggregate["discrepancies"])
    filmstrip = "".join(_filmstrip_cell(row) for row in rows)
    signal_rows = "".join(
        _distribution_row(
            label, cast(Mapping[str, Any], results["quality_signals"])[key]
        )
        for key, label in (
            ("mean_luminance", "Mean luminance"),
            ("clipped_pixel_fraction", "Clipped pixel fraction"),
            ("mean_absolute_gradient", "Mean absolute gradient"),
        )
    )
    segment_rows = "".join(
        _segment_row(name, values)
        for name, values in cast(
            Mapping[str, Mapping[str, Any]], results["by_segment"]
        ).items()
    )
    discrepancy_rows = (
        "".join(
            "<tr>"
            f"<td><code>{escape(str(item['code']))}</code></td>"
            f"<td>{escape(str(item['severity']))}</td>"
            f"<td>{escape(str(item['affected_frames']))}</td>"
            f"<td>{escape(str(item['summary']))}</td>"
            "</tr>"
            for item in discrepancies
        )
        or '<tr><td colspan="4">No discrepancy rules fired.</td></tr>'
    )
    ledger_rows = "".join(_ledger_row(row) for row in rows)
    runtime = cast(
        Mapping[str, Any], cast(Mapping[str, Any], aggregate["pipeline"])["runtime"]
    )
    latency = cast(Mapping[str, Any], results["latency_ms"])
    latency_by_status = cast(
        Mapping[str, Mapping[str, Any]],
        results["latency_ms_by_analysis_status"],
    )
    analyzed_latency = latency_by_status.get("analyzed", {})
    rejected_latency = latency_by_status.get("rejected", {})
    summary = (
        f"{quality['accepted']} of {len(rows)} frames passed both quality layers; "
        f"{verdicts.get('normal', 0)} matched recent history, "
        f"{verdicts.get('uncertain', 0)} were borderline, and "
        f"{verdicts.get('material_scene_change', 0)} were materially different."
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Private corpus replay — visual evidence report</title>
<style>
:root{{--bg:#101714;--panel:#18221e;--line:#31443c;--text:#eef6f1;--muted:#9eb0a7;--ok:#58b987;--warn:#e5b94f;--bad:#df6b67;--off:#66736d}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1400px;margin:auto;padding:24px}}.card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;margin:0 0 16px}}
h1,h2{{margin:0 0 8px}}p{{max-width:85ch}}.notice{{color:var(--warn)}}.scope{{color:var(--muted);font-size:13px}}
.stats{{display:flex;gap:24px;flex-wrap:wrap;margin-top:16px}}.stat b{{display:block;font:22px ui-monospace,monospace}}
.filmstrip{{display:flex;flex-wrap:wrap;gap:7px}}figure{{margin:0;width:100px}}figure img{{display:block;width:100px;height:75px;object-fit:cover;border-radius:5px 5px 0 0;border-bottom:4px solid var(--tone)}}figcaption{{font-size:11px;color:var(--muted)}}
details{{margin-top:14px}}summary{{cursor:pointer;color:#cbe7d8}}table{{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}}th,td{{padding:7px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}code,.mono{{font-family:ui-monospace,monospace}}.scroll{{overflow:auto;max-height:70vh}}
@media print{{body{{background:white;color:black}}.card{{break-inside:avoid;border-color:#bbb;background:white}}details{{display:block}}details>summary{{display:none}}details>*{{display:block!important}}}}
</style></head><body><main>
<section class="card"><h1>Private corpus replay — visual evidence report</h1>
<div class="scope">109 frames · one camera · one Grow Run · run order preserved</div>
<p>{escape(summary)}</p>
<p>This run contains zero real health positives. Specificity is the only plant-adjacent property measurable here; every positive is a scene-change result, never a plant-health diagnosis.</p>
<p class="notice">🔒 Local artefact. Thumbnails and the per-frame ledger stay on this machine. Only aggregate, non-identifying results may be copied into a repository or tracker comment.</p>
<div class="stats">
<span class="stat">Frames<b>{len(rows)}</b></span><span class="stat">Unusable<b>{quality["rejected"]}</b></span>
<span class="stat">Matches history<b>{verdicts.get("normal", 0)}</b></span><span class="stat">Borderline<b>{verdicts.get("uncertain", 0)}</b></span>
<span class="stat">Materially different<b>{verdicts.get("material_scene_change", 0)}</b></span><span class="stat">Discrepancies<b>{len(discrepancies)}</b></span>
</div><hr><div class="scope">Scene-change monitoring only · Plant-health calibration: none in V1</div></section>
<section class="card"><h2>Run timeline</h2><p>One picture per frame in capture order. The single band says what the comparison produced: green normal, amber uncertain, red material scene change, grey unavailable or quality-rejected.</p><div class="filmstrip">{filmstrip}</div></section>
<section class="card"><details><summary>Show the measurements</summary>
<h2>Timing and memory</h2><table><tr><th>Measure</th><th>Value</th></tr>
<tr><td>Vision Analysis latency</td><td class="mono">median {_fmt(latency.get("median"))} ms · p95 {_fmt(latency.get("p95"))} ms · max {_fmt(latency.get("max"))} ms</td></tr>
<tr><td>Analyzed-frame latency</td><td class="mono">median {_fmt(analyzed_latency.get("median"))} ms · p95 {_fmt(analyzed_latency.get("p95"))} ms</td></tr>
<tr><td>Quality-floor rejection latency</td><td class="mono">median {_fmt(rejected_latency.get("median"))} ms · p95 {_fmt(rejected_latency.get("p95"))} ms</td></tr>
<tr><td>Container peak memory</td><td class="mono">{escape(str(runtime.get("memory_peak_human", "unavailable")))}</td></tr></table>
<h2>Quality signals</h2><table><tr><th>Signal</th><th>Count</th><th>Min</th><th>Median</th><th>P95</th><th>Max</th></tr>{signal_rows}</table>
<h2>Distance distributions and verdicts</h2><table><tr><th>Segment</th><th>Frames</th><th>Quality rejected</th><th>Verdicts</th><th>Raw distance distribution</th></tr>{segment_rows}</table>
<h2>Discrepancy ledger</h2><table><tr><th>Code</th><th>Class</th><th>Frames</th><th>Finding</th></tr>{discrepancy_rows}</table>
<h2>Per-frame ledger</h2><div class="scroll"><table><tr><th>#</th><th>Date</th><th>Segment</th><th>Analysis</th><th>Quality</th><th>Baseline</th><th>Distance</th><th>Score</th><th>Verdict</th><th>Latency</th></tr>{ledger_rows}</table></div>
</details></section>
<section class="card scope"><b>Limits.</b> The historical corpus carries neither light-window metadata nor manual Framing Epoch actions. This replay therefore uses light_state=unknown, one synthetic mid-light bucket, and one uninterrupted epoch. Physical arm64 timing and memory are not measured.<br>Scene-change monitoring only · Plant-health calibration: none in V1</section>
</main></body></html>"""


def _filmstrip_cell(row: ReplayRow) -> str:
    tone = {
        "normal": "var(--ok)",
        "uncertain": "var(--warn)",
        "material_scene_change": "var(--bad)",
    }.get(row.verdict or "", "var(--off)")
    title = f"{row.captured_on} · {row.segment} · {row.verdict or row.comparison_outcome or 'unavailable'}"
    return (
        f'<figure style="--tone:{tone}" title="{escape(title)}">'
        f'<img src="{escape(row.thumbnail)}" alt="Private corpus frame {row.index}">'
        f"<figcaption>{escape(row.captured_on[5:])} · {escape(row.segment)}</figcaption></figure>"
    )


def _distribution_row(label: str, raw: Any) -> str:
    values = cast(Mapping[str, Any], raw)
    return (
        f"<tr><td>{escape(label)}</td><td>{values.get('count', 0)}</td>"
        f"<td>{_fmt(values.get('min'))}</td><td>{_fmt(values.get('median'))}</td>"
        f"<td>{_fmt(values.get('p95'))}</td><td>{_fmt(values.get('max'))}</td></tr>"
    )


def _segment_row(name: str, values: Mapping[str, Any]) -> str:
    distribution = cast(Mapping[str, Any], values["raw_distance"])
    rendered = (
        "unavailable"
        if not distribution["count"]
        else f"{_fmt(distribution['min'])} / {_fmt(distribution['median'])} / {_fmt(distribution['p95'])} / {_fmt(distribution['max'])} (min / median / p95 / max)"
    )
    verdicts = ", ".join(f"{key}: {value}" for key, value in values["verdicts"].items())
    return (
        f"<tr><td>{escape(name)}</td><td>{values['frames']}</td>"
        f"<td>{values['quality_rejected']}</td><td>{escape(verdicts)}</td>"
        f'<td class="mono">{escape(rendered)}</td></tr>'
    )


def _ledger_row(row: ReplayRow) -> str:
    quality = "accepted" if row.quality_accepted else ", ".join(row.quality_reasons)
    return (
        f"<tr><td>{row.index}</td><td>{escape(row.captured_on)}</td><td>{escape(row.segment)}</td>"
        f"<td>{escape(row.analysis_status)}</td><td>{escape(quality)}</td>"
        f"<td>{escape(row.baseline_state or '—')} ({row.samples_collected if row.samples_collected is not None else '—'})</td>"
        f'<td class="mono">{_fmt(row.raw_distance)}</td><td class="mono">{_fmt(row.anomaly_score)}</td>'
        f'<td>{escape(row.verdict or row.comparison_outcome or "unavailable")}</td><td class="mono">{row.latency_ms:.1f} ms</td></tr>'
    )


def _multipart_body(image_path: Path, metadata: bytes) -> tuple[bytes, str]:
    boundary = f"growspace-vision-replay-{uuid.uuid4().hex}"
    image_type = mimetypes.guess_type(image_path.name)[0]
    if image_type not in {"image/jpeg", "image/png"}:
        raise ValueError(f"Unsupported corpus image type: {image_path.name}")
    image = image_path.read_bytes()
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="metadata"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        metadata,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="image"; filename="frame{image_path.suffix.lower()}"\r\n'.encode(),
        f"Content-Type: {image_type}\r\n\r\n".encode(),
        image,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _make_thumbnail(source: Path, destination: Path) -> None:
    try:
        from PIL import Image, ImageOps
    except ImportError as error:  # pragma: no cover - exercised by the live environment
        raise RuntimeError(
            "Pillow is required to create the private report thumbnails"
        ) from error
    with Image.open(source) as image:
        thumb = ImageOps.fit(
            image.convert("RGB"), (200, 150), method=Image.Resampling.LANCZOS
        )
        thumb.save(destination, "JPEG", quality=72, optimize=True)


def _distribution(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "median": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "median": statistics.median(ordered),
        "p95": _percentile(ordered, 0.95),
        "max": ordered[-1],
    }


def _percentile(ordered: Sequence[float], quantile: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _container_runtime(container_name: str | None) -> dict[str, Any]:
    runtime: dict[str, Any] = {"host_architecture": platform.machine()}
    if not container_name:
        return runtime
    runtime["container_name"] = container_name
    try:
        inspect = subprocess.run(
            ["docker", "inspect", container_name],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(inspect.stdout)[0]
        runtime["container_image"] = payload["Image"]
        peak = subprocess.run(
            ["docker", "exec", container_name, "cat", "/sys/fs/cgroup/memory.peak"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if peak.isdigit():
            runtime["memory_peak_bytes"] = int(peak)
            runtime["memory_peak_human"] = _human_bytes(int(peak))
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        KeyError,
        IndexError,
        json.JSONDecodeError,
    ):
        runtime["container_metrics"] = "unavailable"
    return runtime


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Vision response {name} is not an object")
    return cast(Mapping[str, Any], value)


def _string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(f"Vision response {name} is not a string array")
    return cast(list[str], value)


def _finite_number(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RuntimeError(f"Vision response {name} is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"Vision response {name} is not finite")
    return number


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _as_f32(values: Sequence[float]) -> tuple[float, ...]:
    """Reproduce the integration's persisted f32 packing before comparison."""
    return struct.unpack(f"<{len(values)}f", struct.pack(f"<{len(values)}f", *values))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _vision_source_provenance() -> dict[str, Any]:
    """Identify production inputs without counting report-only edits as drift."""
    root = Path(__file__).resolve().parents[1]
    production_paths = ("src", "growspace_vision", "Dockerfile", "packaging")
    dirty = _git_value(root, "status", "--porcelain", "--", *production_paths)
    return {
        "repository_commit": _git_value(root, "rev-parse", "HEAD"),
        "production_source_dirty": bool(dirty),
    }


def _human_bytes(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < 1024 or unit == "GiB":
            return f"{amount:.1f} {unit}"
        amount /= 1024
    raise AssertionError("unreachable")


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _read_token(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        token = text.strip()
    else:
        if not isinstance(parsed, dict) or not isinstance(
            parsed.get("access_token"), str
        ):
            raise ValueError("Token JSON must contain a string access_token")
        token = parsed["access_token"]
    if not token or "\n" in token or "\r" in token:
        raise ValueError("Token file must provide one non-empty token")
    return token


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", required=True, type=Path, help="Private 109-frame corpus directory"
    )
    parser.add_argument(
        "--backend-root",
        required=True,
        type=Path,
        help="growspace_manager checkout supplying production rules",
    )
    parser.add_argument(
        "--token-file",
        required=True,
        type=Path,
        help="Raw token or local options.json (never copied to output)",
    )
    parser.add_argument("--service-url", default="http://127.0.0.1:8099")
    parser.add_argument("--output", type=Path, default=Path("private-corpus-report"))
    parser.add_argument(
        "--container-name",
        default="growspace-vision-dev",
        help="Container used for image provenance and peak-memory measurement",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    args = parse_args(arguments)
    frames = discover_corpus(args.corpus.resolve())
    client = VisionClient(args.service_url, _read_token(args.token_file), args.timeout)
    client.container_name = args.container_name
    rules = HomeAssistantRules(args.backend_root)
    _, aggregate = replay(frames, client, rules, args.output.resolve())
    print(f"local_report={args.output.resolve() / 'report.html'}")
    print(f"aggregate={args.output.resolve() / 'aggregate.json'}")
    print(f"discrepancies={len(aggregate['discrepancies'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
