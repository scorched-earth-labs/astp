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
ASTP — Hash Primitive

The single SHA3-256 helper used by every hash construction in the package
(SPEC §5.1). It lives in the protocol layer so that ``astp.protocol`` has no
dependency on ``astp.core``; ``astp.core.schema`` re-exports it.
"""

import hashlib


def sha3_256(data: bytes) -> str:
    """Canonical hash function for all ASTP content hashing. Returns hex string."""
    return hashlib.sha3_256(data).hexdigest()
