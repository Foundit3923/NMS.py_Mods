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
    application: nms_structs.cGcApplication = None
    binoculars: nms_structs.cGcBinoculars = None
    player: nms_structs.cGcPlayer = None
    SolarSystem: nms_structs.cGcSolarSystem = None

    application_ptr: int = 0
    binoculars_ptr: int = 0
    player_ptr: int = 0
    SolarSystem_ptr: int = 0

    SolarSystemName = common.cTkFixedString[0x80]
    UniverseAddress: int = 0
    start_pressing: bool = False
    saved_wp_flag: bool = False
    wpDict: dict = field(default_factory = dict)
    _save_fields_ = ("wpDict", )

@disable
class WaypointManagerMod(NMSMod):
    __author__ = "foundit"
    __description__ = "Place markers at stored waypoints of places you've been"
    __version__ = "1.0"
    __NMSPY_required_version__ = "0.7.0"

    state = State_Vars()
    player_ptr = state.player_ptr

#--------------------------------------------------------------------Init----------------------------------------------------------------------------#

    def __init__(self):
        super().__init__()
        self.name = "WaypointManagerMod"
        self.counter = 0
        self.text = ""
        self.fallingMarker = False
        self.player_pos: common.cTkMatrix34 = None
        self.initial_input = False
        self.ready_for_input = False
        self.f_press_confirmed = False
        self.e_press_confirmed = False

    @on_state_change("MODESELECTOR")
    def init_load_files(self):
        logging.info("Loading files")
        try:
            self.loadJson()
        except Exception as e:
            logging.exception(e)
        logging.info(f'wpDict: {self.state.wpDict}')
        logging.info(f'files loaded for: ({self.name})')       

#--------------------------------------------------Hooks and Functions to Capture and Place Waypoints--------------------------------------------------#

    @main_loop.before
    def do_something(self):
        #logging.info("test")
        #Processes that require main window focus
        if self.state.start_pressing:
            if not keyboard.is_pressed('g') and self.initial_input:
                keyboard.press('g')
                self.initial_input = False
            if self.ready_for_input:
                if not keyboard.is_pressed('f'):
                    keyboard.press('f') 
                logging.info(f'count: {self.counter}, f pressed: {self.f_press_confirmed}, e pressed: {self.e_press_confirmed}')
                if self.counter < 100:
                    if self.f_press_confirmed:
                        if not self.e_press_confirmed:
                            if self.counter > 20:
                                keyboard.press('e')
                    else:
                        keyboard.press('f') 
                    self.counter += 1
                else:
                    keyboard.release('e')
                    keyboard.release('f')
                    self.e_press_confirmed = False
                    self.f_press_confirmed = False
                    self.state.start_pressing = False
                    self.ready_for_input = False
                    self.counter = 0
                    
            if is_main_window_foreground():
                keyboard.release('g')
                self.ready_for_input = True
        #Processes that do not require main window focus
        if self.fallingMarker:
            if self.counter < 100:
                self.counter += 1
            else:
                self.counter = 0
                self.moveWaypoint(self.text)
                self.fallingMarker = False
            
    @one_shot
    @manual_hook(
            "cGcBinoculars::Update",
            pattern="40 55 53 56 41 55 41 56 48 8D AC 24 60",
            func_def=FUNC_CALL_SIGS["cGcBinoculars::Update"],
            detour_time="after",
    )
    def binocUpdate(self, this, *args):
        logging.info(f'--------Binoc Update')
        check = 0
        check += self.state.binoculars_ptr != this
        check += self.state.binoculars == None
        if check:
            logging.info(f'Setting self.state.binoculars')
            self.state.binoculars_ptr = this
            self.state.binoculars = map_struct(this, nms_structs.cGcBinoculars)
            logging.info(f's.s.binoculars_ptr = {self.state.binoculars_ptr}, this = {this}, s.s.binoculars = {self.state.binoculars}')

    @one_shot
    @manual_hook(
            "cGcSolarSystem::Construct",
            pattern="48 89 5C 24 18 48 89 4C 24 08 55 56 57 41 54 41 55 41 56 41 57 48 8D 6C 24 90 48 81 EC 70 01 00 00 83",
            func_def=FUNC_CALL_SIGS["cGcSolarSystem::Construct"],
            detour_time="before",
    )
    def captureSolarSystem(self, this):
        logging.info("SolarSystem.Construct Hook working")
        self.state.SolarSystem = map_struct(this, nms_structs.cGcSolarSystem)
        self.state.SolarSystem_ptr = this

    @one_shot
    @manual_hook(
        "cGcPlayer::UpdateScanning",
        pattern="48 89 5C 24 20 55 56 57 41 54 41 55 41 56 41 57 48 8D AC 24 F0 FA",
        func_def=FUNC_CALL_SIGS["cGcPlayer::UpdateScanning"],
        detour_time="after",
    )
    def capture_player(self, this, val):
        logging.info("--------UpdateScanning hook working")
        logging.info("Setting self.state.player_ptr")
        self.state.player_ptr = this

    @one_shot
    @manual_hook(
        "cGcApplication::Update",
        pattern="40 53 48 83 EC 20 E8 ?? ?? ?? ?? 48 89",
        func_def=FUNCDEF(
            restype=ctypes.c_ulonglong,
            argtypes=[]
        ),
        detour_time="after",
    )
    def captureApplication(self, this):
        logging.info("Application capture hook working")
        logging.info(f'cGcApplication *: {this}')
        if self.state.application_ptr == 0:
            logging.info("Capturing application")
            self.state.application_ptr = this

    @manual_hook(
        "cGcAtmosphereEntryComponent::ActiveAtmosphereEntry",
        pattern="48 89 5C 24 08 57 48 81 EC 80 00 00 00 65 48 8B 04 25 58 00 00 00 48 8B D9",
        func_def=FUNCDEF(
            restype=ctypes.c_int64,
            argtypes=[
                ctypes.c_int64,
            ]
        ),
        detour_time="after",
    )
    def detectFallingMarker(self, this):
        logging.info(f'--------Falling Marker event detected')
        try:
            logging.info(f'self.state.saved_wp_flag == {self.state.saved_wp_flag}')
            if self.state.saved_wp_flag:
              self.state.saved_wp_flag = False
              self.fallingMarker = True
              logging.info(f'self.fallingMarker == {self.fallingMarker}')
        except Exception as e:
            logging.exception(e)
        return this
     
    @manual_hook(
            "cGcBinoculars::SetMarker",
            pattern="40 55 41 56 48 8D AC 24 C8",
            func_def=FUNC_CALL_SIGS["cGcBinoculars::SetMarker"],
            detour_time="before",
    )
    def checkSetMarker(self, this):
        logging.info(f'--------Set Marker event detected')

    #@disable
    @manual_hook(
        "cTkInputPort::SetButton",
        pattern="40 57 48 83 EC 40 48 83 79 58",
        func_def=FUNC_CALL_SIGS["cTkInputPort::SetButton"],
        detour_time="after",
    )
    def get_inputPort(self, this, leIndex):
        if leIndex == 101:
            self.e_press_confirmed = True
        if leIndex == 102:
            self.f_press_confirmed = True

    @on_key_pressed('j')
    def showSave(self):
        logging.info("J pressed")
        logging.info(f'{self.state.application_ptr}')
        if self.state.application_ptr:
            saveSlot = map_struct(0x40, ctypes.c_uint32)
            logging.info(f'Save Slot: {saveSlot}')

#-----------------------------------------------------------------GUI Elements-------------------------------------------------------------------------#

    @gui_button("Print saved waypoints")
    def print_waypoints(self):
        self.print_available_waypoints()

    @property
    @STRING("Save waypoint as: ")
    def option_replace(self):
        return self.text

    @option_replace.setter
    def option_replace(self, location_name):
        self.text = location_name
        set_main_window_focus()
        self.storeLocation(location_name)

    @property
    @STRING("Remove waypoint: ")
    def remove_waypoint(self):
        return self.text

    @remove_waypoint.setter
    def remove_waypoint(self, location_name):
        self.removeWaypointByName(location_name)
        self.updateJson()
        if not self.isWaypointInDictByName(location_name):
            logging.info(f'Successfully removed Waypoint: {location_name}')

    @property
    @STRING("Load waypoint:")
    def load_waypoint_by_name(self):
        return self.text

    @load_waypoint_by_name.setter
    def load_waypoint_by_name(self, waypoint_name):
        self.text = waypoint_name
        logging.info("set_main_window_focus()")
        set_main_window_focus()
        self.initial_input = True
        self.state.saved_wp_flag = True
        logging.info(f'Setting self.state.saved_wp_flag -> {self.state.saved_wp_flag}')
        logging.info(f'start processing: {self.state.start_pressing} -> True')
        self.state.start_pressing = True
    
#--------------------------------------------------------------------Methods----------------------------------------------------------------------------#

#--------------------------------------------------Storing and Loading JSON----------------------------------------------------------#

    def loadJson(self):
        try:
          logging.info(f'Loading dict from local JSON file')
          logging.info(f'self.state.load("waypoint_data.json")')
          self.state.load("waypoint_data.json", True)
        except FileNotFoundError:
            logging.info(f'self.updateJson()')
            self.updateJson()

    def updateJson(self):
        try:
          logging.info(f'Save waypoint locations to local file')
          logging.info(f'self.state.save(\'waypoint_data.json\')')
          self.state.save('waypoint_data.json')
          logging.info(f'dict saved to waypoint_data.json')
        except Exception as e:
                logging.exception(e)

    def storeLocation(self, name):
        try:
          logging.info(f'Save waypoint location to dictionary, then update JSON')
          player_pos = map_struct((self.state.player_ptr + 592), common.cTkMatrix34)
          player_pos_json = player_pos.right.__json__()
          self.updateSolarSystemName()
          self.updateUniverseAddress()
          str_address = str(self.state.UniverseAddress.value)
          try:
            logging.info(f'{self.state.wpDict}')
            if self.state.wpDict.get(str_address):
                self.state.wpDict[str_address][name] = player_pos_json
            else:
                self.addNewUniverseEntry(str_address, name, player_pos_json)
          except Exception as e:
              logging.error(e)          
          self.updateJson()
          logging.info(f'\n')
          return dict
        except Exception as e:
                logging.exception(e) 

    def printDict(self):
        logging.info(self.state.wpDict)
    
    def addNewUniverseEntry(self, str_address, name, player_pos_json):
        solarsystemname = self.state.SolarSystemName.__str__()
        self.state.wpDict[str_address] = {"name": solarsystemname,
                                          name: player_pos_json,
                                          }
    
    def removeWaypointByName(self, name):
        if name is not "name":
            for universe in self.state.wpDict:
                if self.state.wpDict[universe].get(name):
                    del self.state.wpDict[universe][name]
        else:
            logging.info("cannot delete the universe name entry")

    def isWaypointInDictByName(self, name):
        for universe in self.state.wpDict:
            if self.state.wpDict[universe].get(name):
                return True
        return False

#------------------------------------------------------Moving Waypoint--------------------------------------------------------------#

    def moveWaypoint(self, location):
        try:
            logging.info(f'Moving marker')
            MarkerModel = map_struct(ctypes.addressof(self.state.binoculars) + 0x760, common.TkHandle)
            destination_vector = common.Vector3f()
            node_vector = common.Vector3f()
            destination_pos = self.getCoordsFromName(location)
            if self.validDestinationPos(destination_pos):
                destination_vector = self.repackVector3f(destination_pos)
                logging.info(f'destination_vector: ' + destination_vector.__str__())
                node_matrix = engine.GetNodeAbsoluteTransMatrix(MarkerModel)
                logging.info(f'node_matrix: {node_matrix.__str__()}')
                node_vector = node_matrix.pos # type: ignore
                logging.info(f'node_vector: {node_vector.__json__()}')
                transformation_vector = destination_vector - node_vector
                logging.info(f'transformation_vector: ' + transformation_vector.__str__())
                self.moveWaypointToDestination(transformation_vector, MarkerModel)
                logging.info(f'\n')
            else:
                logging.error("That destination is not valid")
        except Exception as e:
                logging.exception(e)

    def moveWaypointToDestination(self, transformation_vector, handle):
        try:
            logging.info(f'Move waypoint to destination')
            try:
                engine.ShiftAllTransformsForNode(handle, transformation_vector)
            except:
                import traceback
                logging.exception(traceback.format_exc())
        except Exception as e:
                logging.exception(e)
    
    def repackVector3f(self, dict_a):
      vector = common.Vector3f()
      vector.x = dict_a['x']
      vector.y = dict_a['y']
      vector.z = dict_a['z']
      return vector

    def getCoordsFromName(self, location):
        coords = {'x': 0, 'y': 0, 'z': 0}
        for address in self.state.wpDict:
            if self.state.wpDict[address].get(location):
                coords = self.state.wpDict[address][location]
        return coords
    
    def validDestinationPos(self, dest):
        if dest['x'] == 0:
            if dest['y'] == 0:
                if dest['z'] == 0:
                    return False
        return True

#------------------------------------------------------Displaying Waypoint Data--------------------------------------------------------------#

    def print_available_waypoints(self):
        dict = self.state.wpDict
        logging.info(f'Available waypoints:')
        logging.info(f'\n{pprint.pformat(dict)}')

#------------------------------------------------------Manage Solar System ID--------------------------------------------------------------#

    def updateSolarSystemName(self):
        name_buff = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        self.state.SolarSystemName = map_struct(name_buff, common.cTkFixedString[0x80])
        call_function(
            "cGcSolarSystem::GetName",
            self.state.SolarSystem_ptr,
            ctypes.addressof(self.state.SolarSystemName),
        )
    
    def updateUniverseAddress(self):
        mUniverseAddress_ptr = self.state.SolarSystem_ptr + 0x22E0
        self.state.UniverseAddress = map_struct(mUniverseAddress_ptr, ctypes.c_uint64)

    def getSolarSystemName(self):
        name_buff = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
        name = map_struct(name_buff, common.cTkFixedString[0x80])
        call_function(
            "cGcSolarSystem::GetName",
            self.state.SolarSystem_ptr,
            ctypes.addressof(name)
        )
        return name.__str__()
    
    def getUniverseAddress(self):
        mUniverseAddress_ptr = self.state.SolarSystem_ptr + 0x22E0
        universeAddress = map_struct(mUniverseAddress_ptr, ctypes.c_uint64)
        return universeAddress