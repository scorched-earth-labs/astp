# Copyright 2026 Scorched Earth Labs, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Coherence Benchmark Contracts
==============================

Dataclasses, enums, and configuration for the Ariadne Coherence Benchmark Suite.
These are the shared types used across all three measurement layers.

Design philosophy:
    Every field has a sensible default so the suite runs out-of-the-box
    against a local Neo4j instance. Override via environment variables or
    by passing a CoherenceConfig explicitly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CoherenceLayer(str, Enum):
    """The three measurement layers in Clotho's coherence framework."""
    STRUCTURAL = "structural"       # Layer 1: infrastructure correctness
    CONTEXTUAL = "contextual"       # Layer 2: retrieval value
    EXPERIENTIAL = "experiential"   # Layer 3: felt continuity


class CoherenceStatus(str, Enum):
    """Result status for an individual benchmark check."""
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class CoherenceConfig:
    """
    Top-level configuration for the coherence benchmark suite.

    All values default to environment variables with sensible fallbacks,
    so the suite runs against a local dev Neo4j instance with no setup.

    Attributes:
        neo4j_uri:          Neo4j bolt URI.
        neo4j_user:         Neo4j username.
        neo4j_password:     Neo4j password.
        neo4j_database:     Neo4j database name.
        embedding_model:    SentenceTransformer model for Layer 2 similarity scoring.
        similarity_threshold: Minimum cosine similarity for contextual relevance pass.
        recency_half_life_days: Half-life for recency weighting in Layer 2.
        drift_window_days:  Lookback window for Layer 3 persona drift detection.
        min_wil_nodes:      Minimum WIL nodes required for a healthy graph (Layer 1).
        run_layer1:         Whether to run structural checks.
        run_layer2:         Whether to run contextual checks.
        run_layer3:         Whether to run experiential checks.
        agent_ids:          List of agent IDs to benchmark. Empty = all agents found.
        episode_limit:      Max episodes to sample per agent in Layer 3.
        output_dir:         Directory for JSON result files. None = no file output.
        verbose:            Emit per-check log lines.
    """

    # Neo4j connection
    neo4j_uri: str = field(
        default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687")
    )
    neo4j_user: str = field(
        default_factory=lambda: os.getenv("NEO4J_USER", "neo4j")
    )
    neo4j_password: str = field(
        default_factory=lambda: os.getenv("NEO4J_PASSWORD", "password")
    )
    neo4j_database: str = field(
        default_factory=lambda: os.getenv("NEO4J_DATABASE", "neo4j")
    )

    # Layer 2 — contextual coherence
    embedding_model: str = "all-MiniLM-L6-v2"
    similarity_threshold: float = 0.72
    recency_half_life_days: float = 14.0

    # Layer 3 — experiential coherence
    drift_window_days: int = 30
    episode_limit: int = 10

    # Layer 1 — structural thresholds
    min_wil_nodes: int = 1

    # Suite control
    run_layer1: bool = True
    run_layer2: bool = True
    run_layer3: bool = True
    agent_ids: List[str] = field(default_factory=list)
    output_dir: Optional[str] = field(
        default_factory=lambda: os.getenv("COHERENCE_OUTPUT_DIR", None)
    )
    verbose: bool = False


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """
    Result of a single benchmark check within a layer.

    Attributes:
        name:       Human-readable check name (e.g. "wil_node_exists").
        status:     Pass / fail / skip / error.
        score:      Numeric score in [0.0, 1.0] where applicable. None for binary checks.
        message:    Explanation of the result.
        metadata:   Arbitrary key-value pairs for drill-down (node counts, query times, etc.).
        duration_ms: How long this check took to execute.
    """
    name: str
    status: CoherenceStatus
    score: Optional[float] = None
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status == CoherenceStatus.PASS

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "score": self.score,
            "message": self.message,
            "metadata": self.metadata,
            "duration_ms": self.duration_ms,
        }


@dataclass
class LayerResult:
    """
    Aggregated result for one coherence layer across all checks.

    Attributes:
        layer:          Which layer this result covers.
        checks:         Individual check results.
        started_at:     When this layer began executing.
        completed_at:   When this layer finished.
        error:          Top-level error if the layer itself failed to run.
    """
    layer: CoherenceLayer
    checks: List[CheckResult] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status == CoherenceStatus.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.checks if c.status == CoherenceStatus.FAIL)

    @property
    def skipped(self) -> int:
        return sum(1 for c in self.checks if c.status == CoherenceStatus.SKIP)

    @property
    def errored(self) -> int:
        return sum(1 for c in self.checks if c.status == CoherenceStatus.ERROR)

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def mean_score(self) -> Optional[float]:
        scored = [c.score for c in self.checks if c.score is not None]
        if not scored:
            return None
        return sum(scored) / len(scored)

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds() * 1000
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer.value,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errored": self.errored,
            "pass_rate": round(self.pass_rate, 4),
            "mean_score": round(self.mean_score, 4) if self.mean_score is not None else None,
            "duration_ms": round(self.duration_ms, 2),
            "error": self.error,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class CoherenceResult:
    """
    Top-level result for a complete coherence benchmark run.

    Contains LayerResults for all three layers plus run-level metadata.
    This is the object returned by CoherenceBenchmarkRunner.run_all().
    """
    run_id: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    config_snapshot: Dict[str, Any] = field(default_factory=dict)
    layers: Dict[CoherenceLayer, LayerResult] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def overall_pass_rate(self) -> float:
        all_checks = []
        for lr in self.layers.values():
            all_checks.extend(lr.checks)
        if not all_checks:
            return 0.0
        passed = sum(1 for c in all_checks if c.status == CoherenceStatus.PASS)
        return passed / len(all_checks)

    @property
    def duration_ms(self) -> float:
        if self.completed_at:
            delta = self.completed_at - self.started_at
            return delta.total_seconds() * 1000
        return 0.0

    def summary(self) -> str:
        """Human-readable summary for CLI output or logs."""
        lines = [
            f"Ariadne Coherence Benchmark — Run {self.run_id}",
            f"  Started:  {self.started_at.isoformat()}",
            f"  Duration: {self.duration_ms:.0f}ms",
            f"  Overall pass rate: {self.overall_pass_rate:.1%}",
            "",
        ]
        for layer, lr in self.layers.items():
            status_icon = "✓" if lr.pass_rate >= 0.8 else "✗"
            score_str = f"  mean_score={lr.mean_score:.3f}" if lr.mean_score is not None else ""
            lines.append(
                f"  [{status_icon}] {layer.value.upper():15s} "
                f"{lr.passed}/{lr.total} passed ({lr.pass_rate:.1%}){score_str}"
            )
            if lr.error:
                lines.append(f"       ERROR: {lr.error}")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": round(self.duration_ms, 2),
            "overall_pass_rate": round(self.overall_pass_rate, 4),
            "error": self.error,
            "config": self.config_snapshot,
            "layers": {k.value: v.to_dict() for k, v in self.layers.items()},
        }
