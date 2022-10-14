# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022 Valory AG
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

"""This package contains round behaviours of PoolManagerAbciApp."""
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Hashable, Optional, Type
from unittest import mock

import pytest

from packages.balancer.contracts.managed_pool_controller.contract import (
    ManagedPoolControllerContract,
)
from packages.balancer.contracts.weighted_pool.contract import WeightedPoolContract
from packages.balancer.skills.pool_manager_abci.behaviours import (
    DecisionMakingBehaviour,
    PoolManagerBaseBehaviour,
    UpdatePoolTxBehaviour,
)
from packages.balancer.skills.pool_manager_abci.rounds import (
    Event,
    FinishedTxPreparationRound,
    FinishedWithoutTxRound,
    SynchronizedData,
)
from packages.valory.contracts.gnosis_safe.contract import GnosisSafeContract
from packages.valory.protocols.contract_api import ContractApiMessage
from packages.valory.protocols.contract_api.custom_types import State
from packages.valory.skills.abstract_round_abci.base import AbciAppDB
from packages.valory.skills.abstract_round_abci.behaviours import (
    BaseBehaviour,
    make_degenerate_behaviour,
)
from packages.valory.skills.abstract_round_abci.test_tools.base import (
    FSMBehaviourBaseCase,
)


SAFE_CONTRACT_ADDRESS = "0x5564550A54EcD43bA8f7c666fff1C4762889A572"
MANAGED_POOL_CONTROLLER_ADDRESS = "0xb821BFfE924E18F8B3d92473C5279d60F0Dfc6eA"
WEIGHTED_POOL_ADDRESS = "0x28BF8d29cFA99aE9C3D876210453272f30e4D131"


@dataclass
class BehaviourTestCase:
    """BehaviourTestCase"""

    name: str
    initial_data: Dict[str, Hashable]
    event: Event
    next_behaviour_class: Optional[Type[PoolManagerBaseBehaviour]] = None


class BasePoolManagerTest(FSMBehaviourBaseCase):
    """Base test case."""

    path_to_skill = Path(__file__).parent.parent

    behaviour: PoolManagerBaseBehaviour  # type: ignore
    behaviour_class: Type[PoolManagerBaseBehaviour]
    next_behaviour_class: Type[PoolManagerBaseBehaviour]
    synchronized_data: SynchronizedData
    done_event = Event.DONE

    def fast_forward(self, data: Optional[Dict[str, Any]] = None) -> None:
        """Fast-forward on initialization"""

        data = data if data is not None else {}
        self.fast_forward_to_behaviour(
            self.behaviour,  # type: ignore
            self.behaviour_class.behaviour_id,
            SynchronizedData(AbciAppDB(setup_data=AbciAppDB.data_to_lists(data))),
        )
        assert (
            self.behaviour.current_behaviour.behaviour_id  # type: ignore
            == self.behaviour_class.behaviour_id
        )

    def complete(
        self, event: Event, next_behaviour_class: Optional[Type[BaseBehaviour]] = None
    ) -> None:
        """Complete test"""
        if next_behaviour_class is None:
            # use the class value as fallback
            next_behaviour_class = self.next_behaviour_class

        self.behaviour.act_wrapper()
        self.mock_a2a_transaction()
        self._test_done_flag_set()
        self.end_round(done_event=event)
        assert (
            self.behaviour.current_behaviour.behaviour_id  # type: ignore
            == next_behaviour_class.behaviour_id
        )


class TestDecisionMakingBehaviour(BasePoolManagerTest):
    """Tests DecisionMakingBehaviour"""

    behaviour_class = DecisionMakingBehaviour
    next_behaviour_class = UpdatePoolTxBehaviour

    _update_required_weights = [80, 10, 10]
    _update_not_required_weights = [60, 30, 10]
    _estimates = {
        "value_estimates": [
            25.0,
            26.0,
        ],
        "timestamp_estimates": [
            1662940800.0,
            1662854400.0,
        ],
    }
    _weighted_pool_error = (  # type: ignore
        f"Couldn't get weights from WeightedPoolContract.get_normalized_weights. "
        f"Expected response performative {ContractApiMessage.Performative.STATE.value}, "  # type: ignore
        f"received {ContractApiMessage.Performative.ERROR.value}."  # type: ignore
    )

    def _mock_weighted_pool_contract_request(
        self,
        response_body: Dict,
        response_performative: ContractApiMessage.Performative,
    ) -> None:
        """Mock the WeightedPoolContract."""
        self.mock_contract_api_request(
            contract_id=str(WeightedPoolContract.contract_id),
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_STATE,
                contract_address=WEIGHTED_POOL_ADDRESS,
            ),
            response_kwargs=dict(
                performative=response_performative,
                state=State(
                    ledger_id="ethereum",
                    body=response_body,
                ),
            ),
        )

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    name="weight update required",
                    initial_data=dict(
                        most_voted_estimates=json.dumps(_estimates),  # type: ignore
                    ),
                    event=Event.DONE,
                ),
                {
                    "mock_response_data": dict(weights=_update_required_weights),
                    "mock_response_performative": ContractApiMessage.Performative.STATE,
                },
            ),
            (
                BehaviourTestCase(
                    name="weight update not required",
                    initial_data=dict(
                        most_voted_estimates=json.dumps(_estimates),  # type: ignore
                    ),
                    event=Event.NO_ACTION,
                    next_behaviour_class=make_degenerate_behaviour(  # type: ignore
                        FinishedWithoutTxRound.round_id
                    ),  # noqa
                ),
                {
                    "mock_response_data": dict(weights=_update_not_required_weights),
                    "mock_response_performative": ContractApiMessage.Performative.STATE,
                },
            ),
        ],
    )
    def test_happy_path(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """The behaviour gets executed without error."""
        self.fast_forward(test_case.initial_data)
        self.behaviour.act_wrapper()

        self._mock_weighted_pool_contract_request(
            response_body=kwargs.get("mock_response_data"),
            response_performative=kwargs.get("mock_response_performative"),
        )

        self.complete(test_case.event, test_case.next_behaviour_class)

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    name="contract error",
                    initial_data=dict(
                        most_voted_estimates=json.dumps(_estimates),  # type: ignore
                    ),
                    event=Event.NO_ACTION,
                    next_behaviour_class=make_degenerate_behaviour(  # type: ignore
                        FinishedWithoutTxRound.round_id
                    ),
                ),
                {
                    "mock_response_data": dict(),
                    "mock_failing_response_performative": ContractApiMessage.Performative.ERROR,
                    "expected_error": _weighted_pool_error,
                },
            )
        ],
    )
    def test_weighted_pool_contract_error(
        self, test_case: BehaviourTestCase, kwargs: Any
    ) -> None:
        """Test Managed Pool Controller Error."""

        with mock.patch.object(self.behaviour.context.logger, "log") as mock_logger:
            self.fast_forward(test_case.initial_data)
            self.behaviour.act_wrapper()

            self._mock_weighted_pool_contract_request(
                response_body=kwargs.get("mock_response_data"),
                response_performative=kwargs.get("mock_failing_response_performative"),
            )

            mock_logger.assert_any_call(
                logging.ERROR,
                kwargs.get("expected_error"),
            )

            self.complete(test_case.event, test_case.next_behaviour_class)


class TestUpdatePoolTxBehaviour(BasePoolManagerTest):
    """Tests UpdatePoolTxBehaviour"""

    behaviour_class = UpdatePoolTxBehaviour

    _weights = [30, 40, 30]
    _pool_controller_error = (
        f"Couldn't get tx data for ManagedPoolControllerContract.update_weights_gradually. "
        f"Expected response performative {ContractApiMessage.Performative.STATE.value}, "  # type: ignore
        f"received {ContractApiMessage.Performative.ERROR.value}."  # type: ignore
    )
    _safe_contract_error = (
        f"Couldn't get safe hash. "
        f"Expected response performative {ContractApiMessage.Performative.STATE.value}, "  # type: ignore
        f"received {ContractApiMessage.Performative.ERROR.value}."  # type: ignore
    )

    def _mock_pool_controller_contract_request(
        self,
        response_body: Dict,
        response_performative: ContractApiMessage.Performative,
    ) -> None:
        """Mock the ManagedPoolControllerContract."""
        self.mock_contract_api_request(
            contract_id=str(ManagedPoolControllerContract.contract_id),
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_STATE,
                contract_address=MANAGED_POOL_CONTROLLER_ADDRESS,
            ),
            response_kwargs=dict(
                performative=response_performative,
                state=State(
                    ledger_id="ethereum",
                    body=response_body,
                ),
            ),
        )

    def _mock_safe_contract_request(
        self,
        response_body: Dict,
        response_performative: ContractApiMessage.Performative,
    ) -> None:
        """Mock the ManagedPoolControllerContract."""
        self.mock_contract_api_request(
            contract_id=str(GnosisSafeContract.contract_id),
            request_kwargs=dict(
                performative=ContractApiMessage.Performative.GET_STATE,
                contract_address=SAFE_CONTRACT_ADDRESS,
            ),
            response_kwargs=dict(
                performative=response_performative,
                state=State(
                    ledger_id="ethereum",
                    body=response_body,
                ),
            ),
        )

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    name="happy path",
                    initial_data=dict(
                        most_voted_weights=_weights,  # type: ignore
                        safe_contract_address=SAFE_CONTRACT_ADDRESS,
                    ),
                    event=Event.DONE,
                    next_behaviour_class=make_degenerate_behaviour(  # type: ignore
                        FinishedTxPreparationRound.round_id
                    ),  # noqa
                ),
                {
                    "mock_response_data": dict(
                        data="0x" + "0" * 64,
                        tx_hash="0x" + "0" * 64,
                    ),
                    "mock_response_performative": ContractApiMessage.Performative.STATE,
                },
            )
        ],
    )
    def test_happy_path(self, test_case: BehaviourTestCase, kwargs: Any) -> None:
        """Test the happy path."""

        with mock.patch(
            "packages.valory.skills.abstract_round_abci.base.AbciApp.last_timestamp",
            return_value=datetime.now(),
        ):
            self.fast_forward(test_case.initial_data)
            self.behaviour.act_wrapper()

            self._mock_pool_controller_contract_request(
                response_body=kwargs.get("mock_response_data"),
                response_performative=kwargs.get("mock_response_performative"),
            )
            self._mock_safe_contract_request(
                response_body=kwargs.get("mock_response_data"),
                response_performative=kwargs.get("mock_response_performative"),
            )

            self.complete(test_case.event, test_case.next_behaviour_class)

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    name="contract error",
                    initial_data=dict(
                        most_voted_weights=_weights,  # type: ignore
                        safe_contract_address=SAFE_CONTRACT_ADDRESS,
                    ),
                    event=Event.NO_ACTION,
                    next_behaviour_class=UpdatePoolTxBehaviour,
                ),
                {
                    "mock_response_data": dict(),
                    "mock_failing_response_performative": ContractApiMessage.Performative.ERROR,
                    "expected_error": _pool_controller_error,
                },
            )
        ],
    )
    def test_managed_pool_controller_error(
        self, test_case: BehaviourTestCase, kwargs: Any
    ) -> None:
        """Test Managed Pool Controller Error."""

        with mock.patch(
            "packages.valory.skills.abstract_round_abci.base.AbciApp.last_timestamp",
            return_value=datetime.now(),
        ), mock.patch.object(self.behaviour.context.logger, "log") as mock_logger:
            self.fast_forward(test_case.initial_data)
            self.behaviour.act_wrapper()

            self._mock_pool_controller_contract_request(
                response_body=kwargs.get("mock_response_data"),
                response_performative=kwargs.get("mock_failing_response_performative"),
            )

            mock_logger.assert_any_call(
                logging.ERROR,
                kwargs.get("expected_error"),
            )

            self.complete(test_case.event, test_case.next_behaviour_class)

    @pytest.mark.parametrize(
        "test_case, kwargs",
        [
            (
                BehaviourTestCase(
                    name="contract error",
                    initial_data=dict(
                        most_voted_weights=_weights,  # type: ignore
                        safe_contract_address=SAFE_CONTRACT_ADDRESS,
                    ),
                    event=Event.NO_ACTION,
                    next_behaviour_class=UpdatePoolTxBehaviour,
                ),
                {
                    "mock_response_data": dict(
                        data="0x" + "0" * 64,
                    ),
                    "mock_response_performative": ContractApiMessage.Performative.STATE,
                    "mock_failing_response_performative": ContractApiMessage.Performative.ERROR,
                    "expected_error": _safe_contract_error,
                },
            )
        ],
    )
    def test_safe_contract_error(
        self, test_case: BehaviourTestCase, kwargs: Any
    ) -> None:
        """Test Safe Contract Error."""

        with mock.patch(
            "packages.valory.skills.abstract_round_abci.base.AbciApp.last_timestamp",
            return_value=datetime.now(),
        ), mock.patch.object(self.behaviour.context.logger, "log") as mock_logger:
            self.fast_forward(test_case.initial_data)
            self.behaviour.act_wrapper()

            self._mock_pool_controller_contract_request(
                response_body=kwargs.get("mock_response_data"),
                response_performative=kwargs.get("mock_response_performative"),
            )
            self._mock_safe_contract_request(
                response_body=kwargs.get("mock_response_data"),
                response_performative=kwargs.get("mock_failing_response_performative"),
            )

            mock_logger.assert_any_call(
                logging.ERROR,
                kwargs.get("expected_error"),
            )

            self.complete(test_case.event, test_case.next_behaviour_class)