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
"""Shared test configuration.

The reference adapter has no feature flag: since 5.1.0 every writer and reader
raises ``AdapterWriteError`` on failure instead of returning a default (SPEC
§15 item 7). Tests that need a store use the driver fakes in their own files.
"""
