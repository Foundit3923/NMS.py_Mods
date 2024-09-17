import logging
import ctypes
import keyboard 
import pygetwindow as gw
import pywinctl as pwc
import pymem
import win32gui
import win32process
from typing import Optional
from dataclasses import dataclass, field
import mouse
import time
from copy import deepcopy
import pprint

import nmspy.data.functions.hooks as hooks
from pymhf.core.hooking import disable, on_key_pressed, on_key_release, manual_hook, one_shot
from pymhf.core.memutils import map_struct
import nmspy.data.structs as nms_structs
from nmspy.data.structs import cGcNGui
from pymhf.core.mod_loader import ModState
from nmspy import NMSMod
from nmspy.decorators import main_loop, on_state_change
from pymhf.core.calling import call_function
from pymhf.gui.decorators import gui_variable, gui_button, STRING
import nmspy.data.local_types as lt
from nmspy.data import common
import nmspy.common as nms
import nmspy.data.engine as engine
from pymhf.gui.gui import GUI
from pymhf.core._types import FUNCDEF
from nmspy.data.functions.call_sigs import FUNC_CALL_SIGS
from pymhf.core.utils import set_main_window_focus, get_main_window, is_main_window_foreground
from nmspy.data.common import TkHandle, Vector3f, cTkMatrix34
#from nmspy.data import engine as engine, common, structs as nms_structs, local_types as lt


@dataclass
class State_Vars(ModState):
    cTkSystem_ptr: int = 0

@disable
class hasFocus(NMSMod):
    __author__ = "foundit"
    __description__ = "Experimenting with cTkSystem::GameHasFocus"
    __version__ = "1.0"
    __NMSPY_required_version__ = "0.7.0"

    state = State_Vars()

#--------------------------------------------------------------------Init----------------------------------------------------------------------------#

    def __init__(self):
        super().__init__()
        self.name = "hasFocus"
        self.print = False


#--------------------------------------------------------------------Hooks----------------------------------------------------------------------------#

    @main_loop.before
    def do_something(self):
        if self.print:
            self.getFocus()
    
    #@disable
    @one_shot
    @hooks.cTkSystem.GameHasFocus.after
    def gameHasFocus(self, this, _result_):
        logging.info(f'----Game Has Focus: {_result_}----')
        self.state.cTkSystem_ptr = this


    @on_key_pressed('u')
    def hasFocus(self):
        logging.info("J key pressed")
        #focus = call_function("cTkSystem::GameHasFocus", self.state.cTkSystem_ptr)
        focus = call_function("glfwGetWindowAttrib", 
                              self.state.cTkSystem_ptr + 50, 
                              131073, 
                              pattern="40 53 48 83 EC 20 83 3D ?? ?? ?? ?? ?? 48 8B D9 75 14", 
                              func_def = FUNCDEF(
                                  restype=ctypes.c_int32,  # int
                                  argtypes=[
                                      ctypes.c_ulonglong,  # cTkSystem *
                                      ctypes.c_int32,      # int
                                  ]
                              ))
        logging.info(f'Game focus: {focus}')

    @on_key_pressed('n')
    def press_k(self):
        self.print = not self.print

    def getFocus(self):
        focus = call_function("glfwGetWindowAttrib", 
                              self.state.cTkSystem_ptr + 50, 
                              131073, 
                              pattern="40 53 48 83 EC 20 83 3D ?? ?? ?? ?? ?? 48 8B D9 75 14", 
                              func_def = FUNCDEF(
                                  restype=ctypes.c_int32,  # int
                                  argtypes=[
                                      ctypes.c_ulonglong,  # cTkSystem *
                                      ctypes.c_int32,      # int
                                  ]
                              ))
        logging.info(f'Game focus: {focus}')
    