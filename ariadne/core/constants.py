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
Protocol-level constants — Amendment v2.0 §1 + §12.

Per the §12 three-tier conformance taxonomy:
  - Wire tier (REQUIRED): schemas, edge types, hash preimages
  - State tier (REQUIRED): lifecycle enums, audit event types
  - Behavioral tier (SOVEREIGN): scoring algorithms, threshold tuning

Threshold constants are **defaults**, not mandates. Implementations are
free to use their own values — what the protocol requires is that the
threshold value at the time of an inference event is recorded on the
audit record (the audit-the-decision pattern from §12.2). The defaults
here exist so a fresh implementation has a sane starting point.

Calibration narrative per §1:
  - Begin conservative.
  - The `CANDIDATE_REJECTED` audit signal (events for candidates below
    DISCOVERY_THRESHOLD) is the primary input for threshold tuning.
  - High rejection rate at scores just above DISCOVERY_THRESHOLD → raise.
  - Low proposal rate combined with known missed links → lower.

Implementations that need runtime-adjustable thresholds (e.g., the SEL
implementation per amendment §11.1.4 stores them in Redis at
`ariadne:thresholds:link_inference`) should read those values at the
time of each inference event and pass them to the operation functions
explicitly, NOT mutate the constants in this module.
"""

from __future__ import annotations

# Below this score, an inferred candidate is not surfaced for human
# review. Recorded for calibration via CANDIDATE_REJECTED audit events.
DISCOVERY_THRESHOLD: float = 0.75

# At or above this score, an inferred candidate is auto-accepted as a
# link without human review. The LINK_ACCEPTED audit event fires
# directly; LINK_PROPOSED is skipped.
AUTO_ACCEPT_THRESHOLD: float = 0.90
