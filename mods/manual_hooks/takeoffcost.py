import logging
from dataclasses import dataclass

from nmspy.data.functions.call_sigs import FUNC_CALL_SIGS
from pymhf.core.hooking import disable, manual_hook, one_shot
from pymhf.core.mod_loader import ModState
from nmspy import NMSMod
from pymhf.gui.decorators import INTEGER


@dataclass
class TestModState(ModState):
    takeoff_cost = 50


@disable
class TakeOffCost(NMSMod):
    __author__ = "monkeyman192"
    __description__ = "Modify the spaceship takeoff cost"
    __version__ = "0.1"
    __NMSPY_required_version__ = "0.7.0"

    state = TestModState()

    def __init__(self):
        super().__init__()

    @property
    @INTEGER("Takeoff Cost: ")
    def takeoff_cost(self):
        return self.state.takeoff_cost

    @takeoff_cost.setter
    def takeoff_cost(self, value):
        self.state.takeoff_cost = value

    @manual_hook(
        "cGcSpaceshipComponent::GetTakeOffCost",
        offset = 0x1367E40,
        #pattern="40 53 48 83 EC 40 48 8B D9 48 8B 0D ?? ?? ?? ?? 48 8B",
        func_def=FUNC_CALL_SIGS["cGcSpaceshipComponent::GetTakeOffCost"],
        detour_time="after",
    )
    def get_takeoff_cost_after(self, this):
        return self.state.takeoff_cost

    @one_shot
    @manual_hook(
        "cGcSimulation::UpdateRender",
        offset=0x103D300,
        func_def=FUNC_CALL_SIGS["cGcSimulation::UpdateRender"],
        detour_time="after",
    )
    def update_render(self, this):
        logging.info(f"Update render: {this}")