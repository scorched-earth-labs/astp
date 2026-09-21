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
Pure ordering helpers over what a StructuralStore returns. No I/O.
"""


def content_hashes_in_sequence_order(found: dict, segment_ids) -> list:
    """The content hashes of ``segment_ids`` present in ``found`` — the
    ``segment_id -> (sequence_index, content_hash)`` map a
    ``StructuralStore.segment_content_hashes`` read returns — ordered by
    ``sequence_index``, the order the Segments were written."""
    present = [found[str(i)] for i in segment_ids if str(i) in found]
    return [h for _, h in sorted(present, key=lambda t: (t[0] is None, t[0]))]
