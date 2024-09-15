import logging
import ctypes
import keyboard 
import pygetwindow as gw
from dataclasses import dataclass, field

import nmspy.data.functions.hooks as hooks
from pymhf.core.hooking import disable, on_key_pressed, on_key_release
from pymhf.core.memutils import map_struct
import nmspy.data.structs as nms_structs
from pymhf.core.mod_loader import ModState
from nmspy import NMSMod
from nmspy.decorators import main_loop, on_fully_booted, on_state_change
from pymhf.core.calling import call_function
from pymhf.gui.decorators import gui_variable, gui_button, STRING
import nmspy.data.local_types as lt
from nmspy.data import common
import nmspy.common as nms
import nmspy.data.engine as engine
from pymhf.gui.gui import GUI
#from nmspy.data import engine as engine, common, structs as nms_structs, local_types as lt

class Window:
    def __init__(self, name):
      self.name = name
      self.is_stored = False
      self.window = None
  
    def isWindowLaunched(self):
        logging.info(f'Checking if {self.name} is launched')
        if self.name in gw.getAllTitles():
            logging.info(f'{self.name} is launched\n')
            return True
        else:
            logging.info(f'{self.name} is not launched\n')
            return False
        
    def isWindowStored(self):
        logging.info(f'Checking if {self.name} window is stored')
        if self.window == None:
            logging.info(f'{self.name} window not stored\n')
            return False
        else:
            logging.info(f'{self.name} window is already stored\n\n')
            return True
        
    def storeWindow(self):
        if not self.isWindowStored():
            logging.info(f'Storing {self.name} window\n')
            self.window = gw.getWindowsWithTitle(self.name)[0]
            self.is_stored = True

    def isActiveWindow(self):
        logging.info(f'Checking if {self.name} is active window')
        if gw.getActiveWindow().title == self.name:
            logging.info(f'{self.name} is the active window\n')
            return True
        else:
            logging.info(f'{self.name} is not the active window\n\n')
            return False

    def activateWindow(self):
        logging.info(f'Activating {self.name} window')
        if self.isWindowLaunched():
            if self.isWindowStored(): 
                if not self.isActiveWindow():
                    logging.info(f'Changing window focus to {self.name}')
                    self.window.activate()
                    logging.info(f'{self.name} is active window\n\n')
                else:
                    logging.info(f'{self.name} window is already activated\n\n')
            else:
                self.storeWindow()
                self.activateWindow()
        else:
            logging.info(f'Unable to activate {self.name} window')
            logging.info(f'{self.name} window is not launched. Launch window and try again.\n\n')


@dataclass
class State_Vars(ModState):
    binoculars: nms_structs.cGcBinoculars = None
    playerEnv: nms_structs.cGcPlayerEnvironment = None
    player: nms_structs.cGcPlayer = None
    inputPort: nms_structs.cTkInputPort = None
    start_pressing: bool = False
    saved_wp_flag: bool = False
    #gui: GUI = None
    wpDict: dict = field(default_factory = dict)
    _save_fields_ = ("wpDict", )

@disable
class WaypointManagerMod(NMSMod):
    __author__ = "foundit"
    __description__ = "Place markers at stored waypoints of places you've been"
    __version__ = "0.4"
    __NMSPY_required_version__ = "0.7.0"

    state = State_Vars()

#--------------------------------------------------------------------Init----------------------------------------------------------------------------#

    def __init__(self):
        super().__init__()
        self.name = "WaypointManagerMod"
        self.should_print = False
        self.counter = 0
        self.marker_lookup = None
        self.text = ""
        #self.last_saved_flag = False
        self.fallingMarker = False
        #self.gui_storage = gui
        self.nms_window = None
        self.gui_window = None

    @on_fully_booted
    def init_windows(self):
        self.nms_window = Window("No Man's Sky")
        self.nms_window.storeWindow()
        self.gui_window = Window("pyMHF")
        self.gui_window.storeWindow()
        #self.state.gui = self.gui_storage

    @on_state_change("APPVIEW")
    def init_state_var(self):
        try:
            self.loadJson()
        except Exception as e:
            logging.exception(e)
        logging.info(f'wpDict: {self.state.wpDict}')
        self.state.playerEnv = nms.GcApplication.data.contents.Simulation.environment.playerEnvironment        
        sim_addr = ctypes.addressof(nms.GcApplication.data.contents.Simulation)
        self.state.binoculars = map_struct(sim_addr + 74160 + 6624, nms_structs.cGcBinoculars)
        logging.info(f'state var set ({self.name})')
        logging.info(f'\n')

#--------------------------------------------------Hooks and Functions to Capture and Place Waypoints--------------------------------------------------#

    @main_loop.after
    def do_something(self):
        if self.fallingMarker:
            logging.info(f'counter: {self.counter}')
            if self.counter < 100:
                self.counter += 1
            else:
                self.counter = 0
                logging.info(f'self.moveWaypoint("{self.text}")')
                self.moveWaypoint(self.text)
                logging.info("Setting self.state.saved_wp_flag == False")
                self.state.saved_wp_flag = False
                self.fallingMarker = False
        if self.state.start_pressing:
            logging.info(f'Eval in Main self.state.saved_wp_flag == {self.state.saved_wp_flag}')
            keyboard.press('f')
            if self.counter < 4:
                logging.info(f'{self.counter}')
                if self.counter == 3:
                    keyboard.press('e')
                self.counter += 1
            else:
                keyboard.release('e')
                keyboard.release('f')
                self.state.start_pressing = False
                self.counter = 0
    
    """ @hooks.cTkInputPort.SetButton.after
    def capture_key(self, this, leIndex):
        #logging.info(f'cTkInputPort: {this}')
        IP = map_struct(this, nms_structs.cTkInputPort)
        self.state.inputPort = map_struct(this, nms_structs.cTkInputPort)
        #logging.info(f'self.state.inputPort: {self.state.inputPort}')
        #logging.info(f'leIndex: {leIndex}')
        #if leIndex == 102:
        #    logging.info("------------------- F pressed ------------------")
        #logging.info(f'InputPort.port: {IP.port}')
        #logging.info(f'InputPort.buttons: {IP.buttons.ones()}')
        #logging.info(f'InputPort.buttonsPrev: {IP.buttonsPrev.ones()}')
        return this, leIndex

    @hooks.cTkEngineUtils.AddNodes.after
    def catchAddNodes(self, this):
         logging.info(f'--------Add Nodes event detected')
         return this """

    @hooks.cGcAtmosphereEntryComponent.ActiveAtmosphereEntry.after #offset 00D63350
    def detectFallingMarker(self, this):
        logging.info(f'--------Falling Marker event detected')
        try:
            logging.info(f'self.state.saved_wp_flag == {self.state.saved_wp_flag}')
            if self.state.saved_wp_flag:
              self.fallingMarker = True
              logging.info(f'self.fallingMarker == {self.fallingMarker}')
        except Exception as e:
            logging.exception(e)
        return this

    """ @hooks.cGcBinoculars.SetMarker.before
    def checkSetMarker(self, this):
        try:
            logging.info(f'--------SetMarker event detected')
            binoculars = map_struct(this, nms_structs.cGcBinoculars)
            self.state.binoculars = binoculars
            self.marker_lookup = binoculars.MarkerModel.lookupInt
            logging.info(f'\n')
        except Exception as e:
            logging.exception(e)
        return this """

    @hooks.Engine.GetNodeAbsoluteTransMatrix.before
    def modify_node_transform(self, node, absMat):
        if node == self.marker_lookup and self.should_log:
            logging.info("Need to override the passed in absMat")
        return node, absMat
    
    @on_key_pressed("f1")
    def toggle_window_focus(self):
        #logging.info(f'{keyboard._os_keyboard.from_name}')
        logging.info(f'F1 key pressed\n')
        self.toggle_gui_and_game()

#-----------------------------------------------------------------GUI Elements-------------------------------------------------------------------------#
    
    @gui_button("INIT self values")
    def init_values(self):
        self.should_print = False
        self.counter = 0
        self.marker_lookup = None
        self.text = ""
        self.state.saved_wp_flag = False
        self.fallingMarker = False
        self.print_values()

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
        if self.state.nms_window.isActiveWindow(): 
            self.state.nms_window.activateWindow()
            self.storeLocation(location_name)
        else:
            logging.info("Launch the game and try again\n\n")

    @property
    @STRING("Remove waypoint: ")
    def remove_waypoint(self):
        return self.text

    @remove_waypoint.setter
    def remove_waypoint(self, location_name):
        del self.state.wpDict[location_name]
        self.updateJson()
        if not self.state.wpDict[location_name]:
            logging.info(f'Successfully removed Waypoint: {location_name}')

    @property
    @STRING("Load waypoint:")
    def load_waypoint_by_name(self):
        return self.text

    @load_waypoint_by_name.setter
    def load_waypoint_by_name(self, waypoint_name):
        self.text = waypoint_name
        if not self.state.nms_window.isActiveWindow(): 
            self.state.nms_window.activateWindow()
        self.state.saved_wp_flag = True
        logging.info(f'Setting self.state.saved_wp_flag -> {self.state.saved_wp_flag}')
        logging.info(f'start processing: {self.state.start_pressing} -> True')
        self.state.start_pressing = True
    
#--------------------------------------------------------------------Methods----------------------------------------------------------------------------#

#------------------------------------------------------Window Management-------------------------------------------------------------#

    def toggle_gui_and_game(self):
        logging.info(f'Checking active window')
        if self.state.nms_window.isActiveWindow():
            logging.info(f'{self.nms_window.name} is the active window')
            self.state.gui_window.activateWindow()
        else:
            logging.info(f'{self.gui_window.name} is the active window')
            self.state.nms_window.activateWindow()

#--------------------------------------------------Storing and Loading JSON----------------------------------------------------------#

    def loadJson(self):
        try:
          logging.info(f'Loading dict from local JSON file')
          logging.info(f'self.state.load("waypoint_data.json")')
          self.state.load("waypoint_data.json")
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
          self.state.wpDict[name] = self.state.playerEnv.mPlayerTM.pos.__json__()
          self.updateJson()
          logging.info(f'\n')
          return dict
        except Exception as e:
                logging.exception(e) 

    def printDict(self):
        logging.info(self.state.wpDict)

#------------------------------------------------------Moving Waypoint--------------------------------------------------------------#

    def moveWaypoint(self, location):
        try:
            logging.info(f'Moving marker')
            destination_vector = common.Vector3f()
            node_vector = common.Vector3f()
            destination_pos = self.state.wpDict[location]
            destination_vector = self.repackVector3f(destination_pos)
            logging.info(f'destination_vector: ' + destination_vector.__str__())
            node_matrix = self.getNodeMatrix()
            node_vector = node_matrix.pos
            logging.info(f'node_vector: ' + node_vector.__str__())
            transformation_vector = destination_vector - node_vector
            logging.info(transformation_vector.__str__())
            self.moveWaypointToDestination(transformation_vector)
            logging.info(f'\n')
        except Exception as e:
                logging.exception(e)

    def moveWaypointToDestination(self, transformation_vector):
        try:
            logging.info(f'Move waypoint to destination')
            call_function("Engine::ShiftAllTransformsForNode", self.state.binoculars.MarkerModel.lookupInt, ctypes.addressof(transformation_vector))
            logging.info(f'\n')
        except Exception as e:
                logging.exception(e)
    
    def getNodeMatrix(self):
        node_matrix = engine.GetNodeAbsoluteTransMatrix(self.state.binoculars.MarkerModel)
        return node_matrix
    
    def repackVector3f(self, dict_a):
      vector = common.Vector3f()
      vector.x = dict_a['x']
      vector.y = dict_a['y']
      vector.z = dict_a['z']
      return vector

#------------------------------------------------------Displaying Waypoint Data--------------------------------------------------------------#

    def print_available_waypoints(self):
        dict = self.state.wpDict
        count = 0
        logging.info(f'\nAvailable waypoints:')
        for key in dict:
            logging.info(f'{key}: {dict[key]}')
