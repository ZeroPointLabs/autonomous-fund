# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022-2023 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Test the models.py module of the Autonomous Fund."""

from packages.balancer.skills.autonomous_fund_abci.models import SharedState
from packages.valory.skills.abstract_round_abci.test_tools.base import DummyContext


class TestSharedState:  # pylint: disable=too-few-public-methods
    """Test SharedState of FearAndGreedOracle."""

    def test_initialization(  # pylint: disable=no-self-use
        self,
    ) -> None:
        """Test initialization."""
        SharedState(name="", skill_context=DummyContext())  # type: ignore
