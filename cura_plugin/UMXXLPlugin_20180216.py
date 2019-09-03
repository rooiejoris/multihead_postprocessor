from UM.Extension import Extension
from UM.Application import Application
from UM.Preferences import Preferences

from UM.i18n import i18nCatalog
i18n_catalog = i18nCatalog("UMXXLPlugin")

class UMXXLPlugin(Extension):
    def __init__(self):
        super().__init__()

        self._application = Application.getInstance()

        self._global_container_stack = None
        self._global_stack_is_umxxl = False
        self._application.globalContainerStackChanged.connect(self._onGlobalContainerStackChanged)
        self._onGlobalContainerStackChanged()

        self._application.engineCreatedSignal.connect(self._onEngineCreated)
        self._application.getOutputDeviceManager().writeStarted.connect(self._filterGcode)


    def _onGlobalContainerStackChanged(self):
        self._global_container_stack = self._application.getGlobalContainerStack()
        if not self._global_container_stack:
            return

        definition_container = self._global_container_stack.getBottom()
        if definition_container.getId() != "umxxl":
            self._global_stack_is_umxxl = False
            return

        self._global_stack_is_umxxl = True

        # HACK: Move UMXXL_settings to the top of the list of settings
        if definition_container._definitions[len(definition_container._definitions) -1].key == "umxxl_settings":
            definition_container._definitions.insert(0, definition_container._definitions.pop(len(definition_container._definitions) -1))

    def _onEngineCreated(self):
        # Fix setting visibility
        preferences = Preferences.getInstance()
        visible_settings = preferences.getValue("general/visible_settings")
        if not visible_settings:
            # Wait until the default visible settings have been set
            return

        visible_settings_changed = False
        for key in ["umxxl_settings"]:
            if key not in visible_settings:
                visible_settings += ";%s" % key
                visible_settings_changed = True

        if not visible_settings_changed:
            return

        preferences.setValue("general/visible_settings", visible_settings)

        expanded_settings = preferences.getValue("cura/categories_expanded")
        if expanded_settings is None:
            expanded_settings = ""
        for key in ["umxxl_settings"]:
            if key not in expanded_settings:
                expanded_settings += ";%s" % key
        preferences.setValue("cura/categories_expanded", expanded_settings)
        self._application.expandedCategoriesChanged.emit()

    def _filterGcode(self, output_device):
        if not self._global_stack_is_umxxl:
            # only apply our postprocessing script to UMXXL printers
            return

        scene = Application.getInstance().getController().getScene()
        if hasattr(scene, "gcode_list"):
            gcode_list = getattr(scene, "gcode_list")
            if gcode_list:
                if ";UMXXLPROCESSED" not in gcode_list[0]:
                    # get settings from Cura
                    global overlap
                    overlap = self._global_container_stack.getProperty("umxxl_overlap", "value")
                    global perimeters
                    perimeters = self._global_container_stack.getProperty("wall_line_count", "value")
                    debug = self._global_container_stack.getProperty("umxxl_debug", "value")

                    if debug == False:
                        gcode_list = execute(gcode_list)
                        gcode_list[0] += ";UMXXLPROCESSED\n"
                        setattr(scene, "gcode_list", gcode_list)

                else:
                    Logger.log("e", "Already post processed")

'''
custom script
'''

def execute(data):


    # Ultimaker XXL prototype project --NOT FOR DISTRIBUTION--
    # Made by Samir den Haan, sdenhaan189@gmail.com
    # TU Delft, Faculty IDE

    # Import libraries
    import re, math
    import math
    import time
    import sys
    import collections

    # joris, dit zou iets met logging kunnen zijn...!?
    # https://github.com/Ultimaker/Cura/issues/384
    # Logger.log('d',"tada...! +++++++++++++++++++++++++++++++++++++++++++++++++++++")
    # Logger.debug()
    # Define variables
    # filetoread = "XXL_tree01"
    
    #joris is ge-set via plugin interface
    #overlap = 5
    #perimeters = 2
    global econstant
    econstant = 0.0329  # mm extrusion/mm printing, will get updated throughout the print
    externalxcurrent = 0
    stepfactor = 400 / 836
    slaveyoffset = 0  # Y offset of slave
    global f_current
    f_current = 1800
    primenozzlegcode = "G1 E0.5 F2700\n\n"  # joris

    printrangex = 208
    printrangey = 208
    externalxrange = 200
    nozzleoffset = 315
    overlap = 5
    blindspot = nozzleoffset - printrangex + overlap + 2
    machinerange = nozzleoffset + printrangex + externalxrange
    domains = [None] * 8
    global cutlines
    cutlines = [None] * 6
    global layernumber
    layernumber = 0
    isretracted = False
    global layerstartleft
    layerstartleft = True

    ##domains index: [a_left:[0], a_right:[1], b_left:[2], b_right[3], c_left:[4], c_right:[5], d_left:[6], d_right:[7]
    ##cutlines index:[ab_left:[0]    , ab_right:[1]    , bc_left:[2]    , bc_right:[3]    , cd_left:[4]    , cd_right:[5]

    octoprintmarker = ";UMXXL MARKER \n"

    # Define non-input variables
    sublayer_a = ["G968 X0 Y0 E0 ; Sublayer A, needed for postprocessor \n"]
    sublayer_b = ["G968 X0 Y0 E0 ; Sublayer B, needed for postprocessor \n"]
    sublayer_c = ["G968 X0 Y0 E0 ; Sublayer C, needed for postprocessor \n"]
    sublayer_d = ["G968 X0 Y0 E0 ; Sublayer D, needed for postprocessor \n"]
    sublayer_a_prev = ["G968 X0 Y0 E0 ; Sublayer A, needed for postprocessor \n"]
    sublayer_b_prev = ["G968 X0 Y0 E0 ; Sublayer B, needed for postprocessor \n"]
    sublayer_c_prev = ["G968 X0 Y0 E0 ; Sublayer C, needed for postprocessor \n"]
    sublayer_d_prev = ["G968 X0 Y0 E0 ; Sublayer D, needed for postprocessor \n"]
    mastertempfile = []
    slavetempfile = []
    totaloutput = []


    # Define relevant coordinates for toolchanges, returns [domains, cutlines]
    def initlayer(objectminx, objectmaxx):
        # Align left side of total printrange to the left side of the print, repeat for right side
        domains[0] = objectminx - 1
        domains[1] = domains[0] + printrangex
        domains[4] = domains[0] + nozzleoffset
        domains[5] = domains[4] + printrangex
        domains[7] = objectmaxx + 1
        domains[6] = domains[7] - printrangex
        domains[3] = domains[7] - nozzleoffset
        domains[2] = domains[3] - printrangex

        # Check to see print is too large to begin with

        # Hier komt de controle of de print met 1 sublayer gemaakt kan worden
        # Controleer de breedte van het object, controleer dan of een van de sublayers die positie kan behalen

        if (domains[0] < 0 or domains[7] > machinerange):
            sys.exit("ERROR! Print out of bounds!")

        # Check to see if the externalX move is large enough to cover the blindspot
        externalxmove = domains[2] - domains[0]
        if externalxmove <= blindspot:
            print("Notice! Correcting this layer by covering the blind spot with an increased externalX")
            externalxmove = blindspot
            domains[2] = domains[0] + externalxmove
            domains[3] = domains[2] + printrangex
            domains[6] = domains[2] + nozzleoffset
            domains[7] = domains[6] + printrangex
            blindspotcorrected = True
        else:
            blindspotcorrected = False

        # Correcting the blindspot will leave space between objectmaxx and domains[7], attempt to center the printer by distibuting this free space
        # Correcting the blindspot will leave space between objectmaxx and domains[7], attempt to center the printer by distibuting this free space
        if blindspotcorrected == True:
            freespace = (domains[7] - objectmaxx) / 2
            availablemachinerange = min(domains[0], domains[7] - nozzleoffset - printrangex)
            if freespace > availablemachinerange:
                freespace = availablemachinerange - 1

            domains[:] = [x - freespace for x in domains]

        # If the right boundary is crossed when covering the blind spot, one must define the domains from the right side
        if (domains[7] > machinerange and blindspotcorrected == False):
            print("Notice! Correcting this layer by reducing the the externalX to respect rightmost machine boundary")
            domains[7] = machinerange
            domains[6] = domains[7] - printrangex
            domains[3] = domains[7] - nozzleoffset
            domains[2] = domains[3] - printrangex
        elif (domains[7] > machinerange and blindspotcorrected == True):
            print(
            "Notice! Correcting this layer by moving both the right and left positions to the left to respect rightmost machine boundary")
            domains[7] = machinerange
            domains[6] = domains[7] - printrangex
            domains[3] = domains[7] - nozzleoffset
            domains[2] = domains[3] - printrangex
            domains[4] = domains[3] - overlap
            domains[5] = domains[4] + printrangex
            domains[0] = domains[4] - nozzleoffset
            domains[1] = domains[0] + printrangex
        '''
        # Manual hack goes here
        if layernumber >= 0:  # Enter layernumber here
            # Note: Values [0, 1, 4, 5] are the master values
            # Use the domains definitions as stated above to define the other three values
            domains[0] = 80
            domains[1] = domains[0] + printrangex
            domains[4] = 405
            domains[5] = domains[4] + printrangex
    
            # Note: define ONE value from domains [2, 3, 6, 7]
            domains[2] = 275
            domains[3] = 410
            domains[7] = domains[2] + nozzleoffset+printrangex
            domains[6] = domains[2] + nozzleoffset
        # Manual hack ends here
        '''

        # Check for valid overlaps
        overlap_ab = domains[1] - domains[2]
        overlap_bc = domains[3] - domains[4]
        overlap_cd = domains[5] - domains[6]
        if (overlap_ab < overlap or overlap_bc < overlap or overlap_cd < overlap):
            print("ERROR! An ovelap area is nonexistant. Cutline can not be found")
        cut_ab = (domains[2] + domains[1]) / 2
        cut_bc = (domains[4] + domains[3]) / 2
        cut_cd = (domains[6] + domains[5]) / 2
        global cutlines
        cutlines = [cut_ab - overlap / 2, cut_ab + overlap / 2, cut_bc - overlap / 2, cut_bc + overlap / 2,
                    cut_cd - overlap / 2, cut_cd + overlap / 2]
        return domains


    # Create toolchangescripts for this layer
    def layerproperties(objectminx, objectmaxx, externalxcurrent):
        domains = initlayer(objectminx, objectmaxx)
        print(domains)
        print(cutlines)
        x_home_a = domains[0]
        x_home_b = domains[2]
        x_home_c = domains[4]
        x_home_d = domains[6]

        # Take note that the positive externalX is to the left, and we are calculating it here as if it were on the right.
        # Sign gets reversed in toolchangescript gcode
        # global externalxcurrent
        externalxmoveright = domains[2] - externalxcurrent
        externalxmoveleft = domains[2] - domains[0]
        externalxcurrent = externalxcurrent + externalxmoveright - externalxmoveleft
        print(externalxmoveright)

        # Define tool and layerchange sequences
        global startscriptMaster
        startscriptMaster = "; --- MASTER START GCODE ---\n" \
            "T1\n" \
            "G92 E0                 ; Set current externalx position to externalx = 0 \n" \
            "T0\n" \
            "M92 E836            ; set steps/mm \n" \
            "M109 T0 S220.000000\n" \
            "G21                     ; metric values\n" \
            "G90                     ; absolute positioning\n" \
            "M83                     ; relative extrusion\n" \
            "M107                 ; start with the fan off\n" \
            "G28 X Y               ; move X/Y to min endstops\n" \
            "M400                ; Wait for current moves to finish \n" \
            "G92 X0 Y0             ; Printer is in printrange origin, set to zero\n" \
            "G4 P100\n" \
            "G1 X10 Y10 F1800\n" \
            "M601 X10 Y10 Z0 E0 L0 ; wacht op slave\n" \
            "G4 P1\n" \
            "G28 Z                ; move Z to min endstops\n" \
            "G1 Z0.15 F1002\n" \
            "G4 P10\n" \
            "G1 X10 Y10 F1800\n" \
            "T1\n" \
            "M302                  ; allow cold extrudes\n" \
            "M204 T25.00          ; set acceleration for non extrude moves\n" \
            "M203 E50.00         ; set max speed\n" \
            "G91                  ; relative positioning\n" \
            "G1 F2000 Z1          ; move Z up - start hopping\n" \
            "G90                  ; absolute positioning\n" \
            "G4 P20                  ; wait 10ms\n" \
            ";G1 F1200 E" + str(-x_home_a * stepfactor) + "       ; move external X to the right\n" \
            "G1 F1200 E" + str(-x_home_a * 400 / 836) + "       ; move external X to the right\n" \
            "G4 P100               ; wait 5s\n" \
            "G28 X Y              ; move X and Y to min endstops\n" \
            "M400                 ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_a) + " ; printer is in home position A, set to right-side coordinate system\n" \
            "G4 P20                  ; wait 10ms\n" \
            "G91                  ; relative positioning\n" \
            "G1 F2000 Z0          ; move Z down - end hopping\n" \
            "G90                  ; absolute positioning\n" \
            "G4 P20                  ; wait 10ms\n" \
            "M302 S175              ; revert cold extrudes\n" \
            "M204 T3000              ; revert acceleration for non extrude moves\n" \
            "M203 E30              ; revert max speed\n" \
            "G4 P100              ; wait 100ms\n" \
            "T0                      ; move ready, we can print!\n" \
            "G4 P1\n" \
            "M42 P11 S255         ; Geeft klaar-signaal\n" \
            "G4 P200\n" \
            "M42 P11 S0             ; trekt singaal in\n\n"
        global startscriptSlave
        startscriptSlave = "; --- START SCRIPT SLAVE ---\n" \
            "M109 T0 S220.000000\n" \
            "T0\n" \
            "M92 E836            ; set steps/mm\n" \
            "G21                     ; metric values\n" \
            "G90                     ; absolute positioning\n" \
            "M83                     ; relative extrusion\n" \
            "M107                 ; start with the fan off\n" \
            "G28 X Y              ; move X/Y to min endstops\n" \
            "M400                ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_c) + " Y" + str(slaveyoffset) + "                 ; slave starts at 315mm(distance between 2 nozzles) to the right\n" \
            "G4 P100\n" \
            "G0 X" + str(x_home_c + 10) + " Y10 F3000\n" \
            "M42 P11 S255         ; Geeft klaar-signaal\n" \
            "M601 X10 Y10 Z0 E0 L0 ; wacht op slave was nozzleoffset\n" \
            "G4 P200\n" \
            "M42 P11 S0             ; trekt singaal in\n"

        # Change from sublayer A to B
        global toolchangeMasterRight
        toolchangeMasterRight = "; --- TOOL CHANGE MASTER RIGHT---\n" \
            "G1 E-13 F1800          ; retraction\n" \
            "G28 X Y            ; home\n" \
            "M400                 ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_a) + "    ; printer is in home position A, set to left-side coordinate system \n" \
            "G0 X" + str(x_home_a + 10) + " Y10 F8004     ; go to neutral position\n" \
            "M601 X10 Y10 Z0 E0 L0 ; wait for other was x_home_a\n" \
            "G4 P20                  ; wait 10ms\n" \
            "T1\n" \
            "G4 P20                  ; wait 10ms\n" \
            "M302                  ; allow cold extrudes\n" \
            "G4 P20                  ; wait 10ms\n" \
            "M204 T50.00          ; set acceleration for non extrude moves\n" \
            "M203 E100.00          ; set max speed\n" \
            "G91                  ; relative positioning\n" \
            "G1 F2000 Z1          ; move Z up - start hopping\n" \
            "G90                  ; absolute positioning\n" \
            "G4 P20                  ; wait 10ms\n" \
            ";G1 F1200 E" + str(-externalxmoveright * stepfactor) + "         ; move external X to the right\n" \
            "G1 F1200 E" + str(-externalxmoveright * 400 / 836) + "         ; move external X to the right\n" \
            "; debug print stepfactor 400/836 " + str(stepfactor) + "       ; \n" \
            "; debug print extmove " + str(externalxmoveright) + "        ; \n" \
            "G4 P1000                ; wait 5s\n" \
            ";G28 X Y             ; home joris turned it off\n" \
            "M400                 ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_b) + " ; printer is in home position B, set to right-side coordinate system\n" \
            "G4 P20                  ; wait 10ms\n" \
            "G91                  ; relative positioning\n" \
            "G1 F2000 Z-1          ; move Z down - end hopping\n" \
            "G90                  ; absolute positioning\n" \
            "G4 P20                  ; wait 10ms\n" \
            "M302 S175              ; revert cold extrudes\n" \
            "M204 T3000              ; revert acceleration for non extrude moves\n" \
            "M203 E30              ; revert max speed\n" \
            "G4 P100               ; wait 100ms\n" \
            "T0                      ; move ready, we can print!\n" \
            "M42 P11 S255          ; tell other to print\n" \
            "G4 P100              ; wait 100ms\n" \
            "M42 P11 S0              ; back to neutral stage\n" \
            "T0                      ; back to extruder 0\n" \
            "G1 E13.8 F1800          ; prime nozzle\n\n"

        # Change from sublayer B to A
        global toolchangeMasterLeft
        toolchangeMasterLeft = "; --- TOOL CHANGE MASTER LEFT---\n" \
            "G1 E-13 F1800          ; retraction\n" \
            "G28 X Y            ; home\n" \
            "M400                 ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_b) + "                ; Printer is in home position B, set to right coordinate system\n" \
            "G0 X" + str(x_home_b + 10) + " Y10 F1800     ; go to neutral position\n" \
            "M601 X10 Y10 Z0 E0 L0 ; wait for other was x_home_b\n" \
            "G4 P20                  ; wait 10ms\n" \
            "T1\n" \
            "G4 P20                  ; wait 10ms\n" \
            "M302                  ; allow cold extrudes\n" \
            "G4 P20                  ; wait 10ms\n" \
            "M204 T50.00          ; set acceleration for non extrude moves\n" \
            "G4 P20                  ; wait 10ms\n" \
            "M203 E100.00          ; set max speed\n" \
            "G4 P20                  ; wait 10ms\n" \
            "G91                  ; relative positioning\n" \
            "G1 F2000 Z1          ; move Z up - start hopping\n" \
            "G90                  ; absolute positioning\n" \
            "G4 P20                  ; wait 10ms\n" \
            ";G1 F1200 E" + str(externalxmoveleft * stepfactor) + "       ; move external X to the left\n" \
            "G1 F1200 E" + str(externalxmoveleft * 400 / 836) + "       ; move external X to the left\n" \
            "G4 P100               ; wait 5s\n" \
            ";G28 X Y             ; home joris turned it off\n" \
            "M400                 ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_a) + " ; printer is in home position A, set it to left-side coordinate system\n" \
            "G4 P20                  ; wait 10ms\n" \
            "G91                  ; relative positioning\n" \
            "G1 F2000 Z-1          ; move Z down - end hopping\n" \
            "G90                  ; absolute positioning\n" \
            "G4 P20                  ; wait 10ms\n" \
            "M302 S175              ; revert cold extrudes\n" \
            "M92 E836              ; revert steps per mm\n" \
            "M204 T3000              ; revert acceleration for non extrude moves\n" \
            "M203 E30              ; revert max speed\n" \
            "G4 P100               ; wait 100ms\n" \
            "T0                      ; move ready, we can print!\n" \
            "M42 P11 S255          ; tell other to print\n" \
            "G4 P150              ; wait 100ms\n" \
            "M42 P11 S0              ; back to neutral stage\n" \
            "T0                      ; back to extruder 0\n" \
            "G1 E13.8 F1800          ; retract, without results in funky synchronization somehow\n\n"

        # Change from sublayer C to D
        global toolchangeSlaveRight
        toolchangeSlaveRight = "; --- TOOL CHANGE SLAVE RIGHT ---\n" \
            "G1 E-13 F1800         ; retraction\n" \
            "G28 X Y               ; home\n" \
            "M400                ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_c) + " ; printer is in home position c, set it to left-side coordinate system\n" \
            "G0 X" + str(x_home_c + 10) + " Y10 F8004     ; go to neutral position\n" \
            "G1 P5000\n" \
            "M42 P11 S255         ; Tell master done\n" \
            "M601 X10 Y10 Z0 E0 L0 ; wait for master was x_home_c\n" \
            "G28 X Y               ; home\n" \
            "M400                ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_d) + "     ; printer is in home position D, set it to right-side coordinate system\n" \
            "G4 P150\n" \
            "M42 P11 S0             ; back to neutral, slave can print\n" \
            "G1 E13.5 F1800\n\n"

        # Change from sublayer D to C
        global toolchangeSlaveLeft
        toolchangeSlaveLeft = "; --- TOOL CHANGE SLAVE LEFT ---\n" \
            "G1 E-13 F1800         ; retraction\n" \
            "G28 X Y               ; home\n" \
            "M400                ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_d) + "            ; printer is in home position D, set it to right-side coordinate system\n" \
            "G0 X" + str(x_home_d + 10) + " Y10 F1800     ; go to neutral position\n" \
            "G4 P100\n" \
            "M42 P11 S255         ; Tell master done\n" \
            "M601 X10 Y10 Z0 E0 L0 ; wait for master was x_home_d\n" \
            "G28 X Y               ; home\n" \
            "M400                ; Wait for current moves to finish \n" \
            "G92 X" + str(x_home_c) + " ; printer is in home position C, set it to left-side coordinate system\n" \
            "G4 P150\n" \
            "M42 P11 S0             ; back to neutral, slave can print\n" \
            "G1 E13.5 F1800\n\n"

        global layerchangeMaster
        layerchangeMaster = "; --- LAYER CHANGE SCRIPT MASTER ---\n" \
            "G1 E-13 F1800         ; retraction\n" \
            "G0 X" + str(x_home_a + 10) + " Y10             ; go to neutral position\n" \
            "M601 X10 Y10 Z0 E0 L0    ; wait for other\n" \
            "G4 P100                    ; wait 5s, we can print\n" \
            "M42 P11 S255           ; tell other to print\n" \
            "G4 P150                   ; wait 100ms\n" \
            "M42 P11 S0               ; back to neutral stage\n" \
            "G1 E13.5 F1800\n\n"

        global layerchangeSlave
        layerchangeSlave = "; --- LAYER CHANGE SCRIPT SLAVE ---\n" \
            "G1 E-13 F1800         ; retraction\n" \
            "G0 X" + str(x_home_c + 10) + " Y10 F8004        ; go to neutral position\n" \
            "G4 P100\n" \
            "M42 P11 S255         ; Tell master done\n" \
            "M601 X10 Y10 Z0 E0 L0 ; wait for master was x_home_c+10\n" \
            "G4 P150\n" \
            "M42 P11 S0             ; back to neutral\n" \
            "G1 E13.5 F1800\n\n"
        global endscriptMaster
        endscriptMaster = "; --- MASTER END SCRIPT ---\n" \
            "T1\n" \
            "M302                  ; allow cold extrudes\n" \
            "M204 T50.00          ; set acceleration for non extrude moves\n" \
            "M203 E100.00          ; set max speed\n" \
            "G91                  ; relative positioning\n" \
            "G1 F2000 Z1          ; move Z up - start hopping\n" \
            "G90                  ; absolute positioning\n" \
            "G4 P20                  ; wait 10ms\n" \
            ";G1 F1200 E" + str(x_home_a * stepfactor) + "      ; move external X to machine X0\n" \
            "G1 F1200 E" + str(x_home_a * 400 / 836) + "      ; move external X to machine X0\n" \
            "G4 P100             ; wait 5s\n" \
            "G92 X0                  ; printer is in machine X0, set X to 0\n" \
            "G4 P20                  ; wait 10ms\n" \
            "G91                  ; relative positioning\n" \
            "G1 F2000 Z0          ; move Z down - end hopping\n" \
            "G90                  ; absolute positioning\n" \
            "G4 P20                  ; wait 10ms\n" \
            "M302 S175              ; revert cold extrudes\n" \
            "M204 T3000              ; revert acceleration for non extrude moves\n" \
            "M203 E30              ; revert max speed\n" \
            "G4 P100              ; wait 100ms\n" \
            "T0                      ; move ready, we can print!\n" \
            "M104 S0     ; turn off extruder\n" \
            "M140 S0     ; turn off bed\n" \
            "M84         ; disable motors\n\n"
        global endscriptSlave
        endscriptSlave = "; --- SLAVE END SCRIPT ---\n" \
            "M104 S0     ; turn off extruder\n" \
            "M140 S0     ; turn off bed\n" \
            "M84         ; disable motors\n\n"


    # Define class to read file
    class filereader:
        '''
        sourcefile = str(filetoread) + ".gcode" # Specify source file here
        totalgcode = ""

        with open(sourcefile,'r+') as r:  # Read lines from source file
            totalgcode = r.readlines()    # Total gcode is a list of lines
        '''
        totalgcode = data

    # Function that writes the processed gcode to a file. Not used in the cura plugin
    def filewriter(data, filename):
        targetfile = str(filename) + ".gcode"  # #Specify target file
        with open(targetfile, 'w') as w:
            for i in data:
                w.write(i)


    # Function that returns the value after a specific key, use to retrieve gcode argument values
    def getValue(line, key, default=None):
        if not key in line or (';' in line and line.find(key) > line.find(';')):
            return default
        subPart = line[line.find(key) + 1:]
        m = re.search('^[0-9]+\.?[0-9]*|^-[0-9]+\.?[0-9]*', subPart)
        if m == None:
            return default
        try:
            return round(float(m.group(0)), 5)
        except:
            return default


    # Function that returns the last known toolhead X,Y and E position from a specific sublayer
    def lastknownposition(sublayer, startpoint=1):
        if startpoint <= len(sublayer):
            n = startpoint
        else:
            n = len(sublayer)
        if startpoint <= len(sublayer):
            m = startpoint
        else:
            m = len(sublayer)
        if startpoint <= len(sublayer):
            p = startpoint
        else:
            p = len(sublayer)

        # Iterate through last lines in sublayer to find current toolhead position
        while getValue(sublayer[-n], "X", -1) == -1:
            n += 1  # find last line that provided an X position.
        else:
            lastx = getValue(sublayer[-n], "X", None)  # Note the last known X position

        while getValue(sublayer[-m], "Y", -1) == -1:
            m += 1  # find last line that provided a Y position
        else:
            lasty = getValue(sublayer[-m], "Y", None)  # Note the last known Y position

        while getValue(sublayer[-p], "E", -1) == -1:
            p += 1  # find last line that provided an E move
        else:
            laste = getValue(sublayer[-p], "E", None)  # Note the last known E move

        return lastx, lasty, laste


    # Function that checks if the toolhead moved with respect to its last position
    # Returns [Is the current point not move at all?, Did the current current point move past a cutline?]
    def checkduplicate(line, sublayer):
        lastx, lasty, laste = lastknownposition(sublayer)
        if (line.find("X") == -1 and line.find("Y") and line.find("E") != -1):
            isretraction = True
        else:
            isretraction = False

        if (line.find("X") == -1):  # Note the current X and Y positions, and compare
            currentx = lastx
        else:
            currentx = getValue(line, "X", None)
        if line.find("Y") == -1:
            currenty = lasty
        else:
            currenty = getValue(line, "Y", None)

        if isretraction == False:
            isduplicate = False
        elif currentx == lastx and currenty == lasty:  # Point is a duplcate when both X and Y have not moved and move is not a retraction
            isduplicate = True
        else:
            isduplicate = False

        if isretraction == True:
            issublayerwall = False
        elif currentx == lastx and currenty != lasty:  # Point is a sublayer wall when X has not moved while Y has
            issublayerwall = True
        else:
            issublayerwall = False
        return isduplicate, issublayerwall


    def minmax(layer):  # Function that takes the maximum and minimum X and Y of a layer
        # Base values
        machinewidth = 355  # width of 1 ultimaker unit
        maxexternalx = 205  # maximum externalx range
        machinerange = 2 * machinewidth + maxexternalx
        z = 50
        x = 50
        y = 50
        maxX = 0
        maxY = 0
        minX = 999
        minY = 999
        maxZ = 999

        for currentline in layer:
            if getValue(currentline, 'G', None) == 1 or getValue(currentline, 'G', None) == 0:
                # maxZ = getValue(currentline, "Z", maxZ)
                x = getValue(currentline, "X", x)
                y = getValue(currentline, "Y", y)
                #                            print(x)
                # max en min x en y uitzoeken
                if x > maxX: maxX = x
                if x < minX: minX = x
                if y > maxY: maxY = y
                if y < minY: minY = y

        midpoint = (minX + maxX) / 2
        if midpoint < machinewidth:
            midpoint = machinewidth
        if midpoint > machinerange - machinewidth:
            midpoint = machinerange - machinewidth

        # print("min x: " + str(minX) + ", max x: " + str(maxX))
        # print("totObjWidth: " + str(maxX-minX))
        # print("midpoint absolute: " + str(((maxX-minX)/2)+minX))
        return minX, maxX, minY, maxY


    # Function to change the absolute E values of a Gcode to their relative counterparts
    def relativeE(totalgcode):  # Method to make all E arguments relative
        # Base values
        count = 0
        e_previous = 0
        e_current = 0

        for currentline in totalgcode:
            # print(currentline)
            # print("Instance " + str(count) + " Value " + str(e_previous))
            if "e" in currentline:  # Capitalize our E values for easy searching
                currentline.replace("e", "E")
            if "E" in currentline:  # Look for lines with extrusion commands
                if currentline.find("G92") >= 0:  # If line is a G92, use G92 value as previous E
                    # print("G92 found in " + str(count))
                    e_preG92 = e_previous
                    e_value = getValue(currentline, "E", None)
                    if e_value != None:
                        e_previous = e_value
                elif (currentline.find('E') < currentline.find(';')) or (currentline.find("E") > 0 and currentline.find(
                        ';') == -1):  # Only process line if extrusion is not a comment
                    lineindex = totalgcode.index(currentline)
                    e_current = getValue(currentline, "E", e_current)
                    e_relative = e_current - e_previous
                    e_relative = round(e_relative, 5)
                    e_previous = round(e_current, 5)
                    currentline = re.sub("E\d+[.]\d+", "E" + str(e_relative),
                                         currentline)  # Replace old E value with new E value
                    totalgcode[lineindex] = currentline  # Replace old command with new command
            count += 1
            print("Relative E, count = " + str(count))


    # Function to extract the layers from the gcode, returns a list of lists
    def fetchlayer(totalgcode):
        layers = []
        currentlayer = []
        for currentline in totalgcode:
            if currentline.find(
                    ";LAYER:") >= 0:  # ";LAYER" is a layer change script used in the standard setup of Cura (current version:2.7.0), might need adjustment in the future
                layers.append(currentlayer)
                currentlayer = []
            currentlayer.append(currentline)  # Add line to list of lines for this layer
        layers.append(currentlayer)  # Add layer to list of layers for this gcode
        return layers


    # Function to find the angle of a line, used to calculate the cut sections
    def findangle(x_l, y_l, x_r, y_r):
        delta_x = x_r - x_l
        delta_y = y_r - y_l
        tan = delta_y / delta_x
        angle = math.atan(tan)
        return angle


    # Simple logic table that checks if any of the cutlines is crossed
    def cutlinecrossed(x_current, x_previous, cutlines):
        linescrossed = []
        for value in cutlines:
            if x_current <= value and x_previous <= value:
                linescrossed.append(False)
            elif x_current <= value and x_previous >= value:
                linescrossed.append(True)
            elif x_current >= value and x_previous <= value:
                linescrossed.append(True)
            elif x_current >= value and x_previous >= value:
                linescrossed.append(False)
            else:
                print("Cutline check " + value + "Failed!")
        return linescrossed


    # Function that halves the extrusion amount when printing an overlap
    def halfextrusion(line):
        e = getValue(line, "E", None)
        if e != None:
            line = re.sub("E\d+[.]\d+", "E" + str(e / 2), line)
        return line


    # Function that determines the extrusionconstant at a certain point, defaults to preset value if not found
    def updateeconstant(x_current, y_current, e_current, x_previous, y_previous):
        global econstant
        length = math.sqrt((x_previous - x_current) ** 2 + (y_previous - y_current) ** 2)
        if length == 0 or e_current == 0:
            econstant = econstant
        else:
            econstant = e_current / length
        return econstant


    # Function that reduces the inside sidewalls of a sublayer proportional to the amount of outer perimeters
    def sublayerwallextrusion(line, sublayer):
        e = getValue(line, "E", None)
        y = getValue(line, "Y", None)
        lastx, lasty, laste = lastknownposition(sublayer)
        if e != None:
            length = abs(y - lasty)
            extrusion = (length * econstant) / perimeters
            line = re.sub("E\d+[.]\d+", "E" + str(extrusion), line)
        return line


    # Function that brings a non-cutline crossing movement line to a sublayer
    def courier(line, x_left, x_right):
        # Cases in which the line is in the overlap between 2 sublayers
        if (x_left <= cutlines[1] and x_right <= cutlines[1] and x_left >= cutlines[0] and x_right >= cutlines[0]):
            duplicating_a, sublayerwall_a = checkduplicate(line, sublayer_a)
            duplicating_b, sublayerwall_b = checkduplicate(line, sublayer_b)

            if duplicating_a == True:
                line_a = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_a == True:
                line_a = sublayerwallextrusion(line, sublayer_a)
            else:
                line_a = halfextrusion(line)

            if duplicating_b == True:
                line_b = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_b == True:
                line_b = sublayerwallextrusion(line, sublayer_b)
            else:
                line_b = halfextrusion(line)

            sublayer_a.append(line_a)
            sublayer_b.append(line_b)

        elif (x_left <= cutlines[3] and x_right <= cutlines[3] and x_left >= cutlines[2] and x_right >= cutlines[2]):
            duplicating_b, sublayerwall_b = checkduplicate(line, sublayer_b)
            duplicating_c, sublayerwall_c = checkduplicate(line, sublayer_c)
            if duplicating_b == True:
                line_b = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_b == True:
                line_b = sublayerwallextrusion(line, sublayer_b)
            else:
                line_b = halfextrusion(line)

            if duplicating_c == True:
                line_c = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_c == True:
                line_c = sublayerwallextrusion(line, sublayer_c)
            else:
                line_c = halfextrusion(line)

            sublayer_b.append(line_b)
            sublayer_c.append(line_c)

        elif (x_left <= cutlines[5] and x_right <= cutlines[5] and x_left >= cutlines[4] and x_right >= cutlines[4]):
            duplicating_c, sublayerwall_c = checkduplicate(line, sublayer_c)
            duplicating_d, sublayerwall_d = checkduplicate(line, sublayer_d)

            if duplicating_c == True:
                line_c = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_c == True:
                line_c = sublayerwallextrusion(line, sublayer_c)
            else:
                line_c = halfextrusion(line)

            if duplicating_d == True:
                line_d = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_d == True:
                line_d = sublayerwallextrusion(line, sublayer_d)
            else:
                line_d = halfextrusion(line)

            sublayer_c.append(line_c)
            sublayer_d.append(line_d)

        # Cases in which the line is in a single subdomain
        elif (x_left <= cutlines[0] and x_right <= cutlines[0] and x_left >= domains[0] and x_right >= domains[0]):
            duplicating_a, sublayerwall_a = checkduplicate(line, sublayer_a)
            if duplicating_a == True:
                line = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_a == True:
                line = sublayerwallextrusion(line, sublayer_a)
            else:
                line = line

            sublayer_a.append(line)

        elif (x_left <= cutlines[2] and x_right <= cutlines[2] and x_left >= cutlines[1] and x_right >= cutlines[1]):
            duplicating_b, sublayerwall_b = checkduplicate(line, sublayer_b)
            if duplicating_b == True:
                line = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_b == True:
                line = sublayerwallextrusion(line, sublayer_b)
            else:
                line = line

            sublayer_b.append(line)

        elif (x_left <= cutlines[4] and x_right <= cutlines[4] and x_left >= cutlines[3] and x_right >= cutlines[3]):
            duplicating_c, sublayerwall_c = checkduplicate(line, sublayer_c)
            if duplicating_c == True:
                line = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_c == True:
                line = sublayerwallextrusion(line, sublayer_c)
            else:
                line = line

            sublayer_c.append(line)

        elif (x_left <= domains[7] and x_right <= domains[7] and x_left >= cutlines[5] and x_right >= cutlines[5]):
            duplicating_d, sublayerwall_d = checkduplicate(line, sublayer_d)
            if duplicating_d == True:
                line = re.sub("E\d+[.]\d+", "E0", line)
            elif sublayerwall_d == True:
                line = sublayerwallextrusion(line, sublayer_d)
            else:
                line = line
            sublayer_d.append(line)

        else:
            print("Courier failed! " + str(line) + "(x_left: " + str(x_left) + " x_right: " + str(x_right) + ")\n")


    # Function that identifies a line to be cut and cuts it in two pieces that do not cross a cutline
    def cutter(linetocut, cutline, x_current, y_current, x_previous, y_previous):
        # Orient line from left to right to comply with cutline-check order
        if min(x_current, x_previous) == x_previous:
            leftapproach = True
            x_l = x_previous
            y_l = y_previous
            x_r = x_current
            y_r = y_current
        elif x_current < x_previous:
            leftapproach = False
            x_l = x_current
            y_l = y_current
            x_r = x_previous
            y_r = y_previous
        else:
            print('Aligning line from left to right in the cutter went wrong! How is that even possible?')

        # duplicate the line to split in two
        cutpoint = linetocut

        # calculate the point where the line is to be cut
        a = round(findangle(x_previous, y_previous, x_current, y_current), 4)
        x_mid = cutline
        y_mid = y_previous + (math.tan(a) * (x_mid - x_previous))

        # Calculate extrusion values
        if linetocut.find("E") != -1:
            e = getValue(linetocut, "E", None)
            firstsection = (x_mid - x_previous) / (x_current - x_previous)
            e_mid = e * firstsection
            e_end = e * (1 - firstsection)
            linetocut = re.sub("E\d+[.]\d+", "E" + str(e_end), linetocut)
            cutpoint = re.sub("E\d+[.]\d+", "E" + str(e_mid), cutpoint)

        # Edit pre-cutpoint line by changing the endpoint to coincide with the cutline, then use the courier to place it in a sublayer

        cutpoint = re.sub("X\d+[.]\d+", "X" + str(x_mid), cutpoint)
        cutpoint = re.sub("Y\d+[.]\d+", "Y" + str(y_mid), cutpoint)
        movetocutpoint = cutpoint

        courier(cutpoint, x_previous, x_mid)

        # Use the courier to place the move to the cutpoint in the adjacent sublayer, only when crossing into one
        if (cutline == cutlines[1] or cutline == cutlines[3] or cutline == cutlines[5]) and leftapproach:
            x_overshoot = x_mid + 1
            courier(movetocutpoint, x_mid, x_overshoot)
        if (cutline == cutlines[1] or cutline == cutlines[3] or cutline == cutlines[5]) and not leftapproach:
            x_overshoot = x_mid - 1
            courier(movetocutpoint, x_mid, x_overshoot)

        elif (cutline == cutlines[0] or cutline == cutlines[2] or cutline == cutlines[4]) and not leftapproach:
            x_overshoot = x_mid - 1
            courier(movetocutpoint, x_mid, x_overshoot)
        elif (cutline == cutlines[0] or cutline == cutlines[2] or cutline == cutlines[4]) and leftapproach:
            x_overshoot = x_mid + 1
            courier(movetocutpoint, x_mid, x_overshoot)

        # return the cutpoint position to define as x_previous and y_previous in the distributor
        return (x_mid, y_mid, linetocut)


    # Function that extracts current and previous coordinates per line distributes lines over sublayers A,B,C and D based on their position
    # This function uses cutter(identify lines to be cut, and create 2 lines that fit within an area)
    # Assumption: there is no gcode line that issues a G0 or G1 with an X value that is executed and a Y value that is commented, or vice versa
    def distributor(layer):
        x_current = 108  # 10
        y_current = 108  # 10
        x_previous = 108  # 10
        y_previous = 108  # 10
        lastassign = "a"
        splitlayer = layer.splitlines()

        for line in splitlayer:
            line = line + "\n"
            x_pos = line.find("X")
            y_pos = line.find("Y")
            z_pos = line.find("Z")
            f_pos = line.find("F")
            e_pos = line.find("E")
            comment_pos = line.find(";")

            x_previous = x_current  # Save last X value
            y_previous = y_current  # Save last Y value
            if f_pos != -1:
                global f_current
                f_current = getValue(line, 'F', None)

            count = 0

            # Triggers when a G1 command containing Z is issued
            if (comment_pos == -1 and z_pos != -1) or ((comment_pos > z_pos) and z_pos != -1):
                z_current = getValue(line, 'Z', None)
                extractedzmove = "G1 Z" + str(z_current) + "\n"
                if lastassign == "a" or lastassign == "c":
                    sublayer_a.append(extractedzmove)
                    sublayer_b.append(extractedzmove)
                    sublayer_c.append(extractedzmove)
                    sublayer_d.append(extractedzmove)
                else:
                    print("Distribution error: non-movement command not distributed")

            # Line is a comment when a semicolon is present earlier in the line than the X or Y character. Will get placed in sublayer A and C.
            if comment_pos != -1 and (comment_pos < x_pos or comment_pos < y_pos):
                sublayer_a.append(line)
                sublayer_c.append(line)

            # Line is not a comment and contains Z movement, Z movement is to be extracted into a separate line, and written to master and slave, A/C or B/D depends on last assignment


            # Line is not a comment, and no G0/G1, will get placed in both master and slave, A/B or C/D depends on last assignment
            elif comment_pos == -1 and line.find("G0") == -1 and line.find("G1") == -1:
                if lastassign == "a" or lastassign == "c":
                    sublayer_a.append(line)
                    sublayer_c.append(line)
                elif lastassign == "b" or lastassign == "d":
                    sublayer_b.append(line)
                    sublayer_d.append(line)
                else:
                    print("Distribution error: non-movement command not distributed")



            # Line is not a comment and contains XY movement coordinates (should only be G0 or G1)
            elif comment_pos == -1 or (comment_pos > x_pos or comment_pos > y_pos):

                if f_pos == -1:
                    line = re.sub("\n", " F" + str(f_current) + " \n", line)
                if getValue(line, "X", None) != None:  # Only take new X value if present
                    x_current = getValue(line, "X", None)
                else:
                    x_idle = True
                if getValue(line, "Y", None) != None:
                    y_current = getValue(line, "Y", None)  # Only take new Y value if present
                else:
                    y_idle = True
                if e_pos != -1:  # Update E constant after X and Y are updated
                    e_current = getValue(line, "E", 0)
                    updateeconstant(x_current, y_current, e_current, x_previous, y_previous)

                # When a cutline is crossed, split the line using the cutter method, then distribute its left part with the courier method, then keep right part to check other cutlines

                # Check for crossing Min and Max X lines, not needed as Cura will not slice any objects out of its printrange
                # if cutlinecrossed(x_current,x_previous, minx) == True:
                #     print("Warning! Minimum X crossed (x_current: " + str(x_current) + ", x_previous: " + str(x_previous) +  ", minx: " + str(minx) + ")")
                # if cutlinecrossed(x_current,x_previous, maxx) == True:
                #     print("Warning! Maximum X crossed (x_current: " + str(x_current) + ", x_previous: " + str(x_previous) +  ", maxx: " + str(maxx) + ")")

                # In case line runs from left to right, check all cutlines and cut them where needed
                if x_current > x_previous:
                    linescrossed = cutlinecrossed(x_current, x_previous, cutlines)
                    i = 0
                    for cut in linescrossed:
                        if cut == True:
                            cutpos = cutter(line, cutlines[i], x_current, y_current, x_previous, y_previous)
                            line = cutpos[2]  # Continue using the edited line
                            x_previous = cutpos[0]  # Take X value of remaining right side of line
                            y_previous = cutpos[1]  # Take Y value of remaining right side of line
                        i += 1
                    courier(line, x_current, x_previous)

                # And when the line runs right to left, start checking at the rightmost cutline
                elif x_current < x_previous:
                    linescrossed = (cutlinecrossed(x_current, x_previous, cutlines))
                    reverselinescrossed = reversed(linescrossed)
                    i = -1
                    for cut in linescrossed[::-1]:
                        if cut == True:
                            cutpos = cutter(line, cutlines[i], x_current, y_current, x_previous, y_previous)
                            line = cutpos[2]  # Continue using the edited line
                            x_previous = cutpos[0]  # Take X value of remaining left side of line
                            y_previous = cutpos[1]  # Take Y value of remaining left side of line
                        i -= 1
                    courier(line, x_current, x_previous)

                # Only the part right of any cutline should remain at this point, the courier will place it in the correct sublayer
                elif x_current == x_previous:

                    if y_current == y_previous and e_pos != -1:  # this is a retraction
                        if isretracted == False:
                            isretracted == True
                            retractpos = [x_current, y_current]
                            courier(line, retractpos[0], retractpos[0])
                        elif isretracted == True:
                            isretracted == False
                            courier(line, retractpos[0], retractpos[0])

                    else:
                        courier(line, x_current, x_previous)

                    # print(str(line) + " has x " + str(x_current)+ " and " + str(x_previous))


    # Function to edit the first move of a sublayer as such that it does not extrude when approaching the print from home
    def firstsublayermove(sublayer):
        for linecounter, line in enumerate(sublayer):
            if line.find("G1") != -1 and line.find("E") != -1:
                line = re.sub("G1", "G0", line)
                line = re.sub("E\d+[.]\d+", "E0", line)
                sublayer[linecounter] = line
                sublayer.insert(linecounter + 1, primenozzlegcode)
                break
            elif line.find("G0") != -1:
                sublayer.insert(linecounter + 1, primenozzlegcode)
                break
        return sublayer


    # Function that slots the sublayers and tool/layerchange scripts into the correct tempfile in the correct order
    def recombinelayer(sublayer_a, sublayer_b, sublayer_c, sublayer_d):
        global layerstartleft
        sublayer_a = firstsublayermove(sublayer_a)
        sublayer_b = firstsublayermove(sublayer_b)
        sublayer_c = firstsublayermove(sublayer_c)
        sublayer_d = firstsublayermove(sublayer_d)

        if layerstartleft == True:
            a = ''.join(sublayer_a)
            a = a + toolchangeMasterRight
            mastertempfile.append(a)
            b = ''.join(sublayer_b)
            b = b + layerchangeMaster
            mastertempfile.append(b)
            c = ''.join(sublayer_c)
            c = c + toolchangeSlaveRight
            slavetempfile.append(c)
            d = ''.join(sublayer_d)
            d = d + layerchangeSlave
            slavetempfile.append(d)
            layerstartleft = False

        elif layerstartleft == False:
            b = ''.join(sublayer_b)
            b = b + toolchangeMasterLeft
            mastertempfile.append(b)
            a = ''.join(sublayer_a)
            a = a + layerchangeMaster
            mastertempfile.append(a)
            d = ''.join(sublayer_d)
            d = d + toolchangeSlaveLeft
            slavetempfile.append(d)
            c = ''.join(sublayer_c)
            c = c + layerchangeSlave
            slavetempfile.append(c)
            layerstartleft = True


    # Method that places every line in the mastertempfile list in a totaloutput list, followed by the octoprint marker and the lines of the tempslavefile list
    def combinemasterslave(mastertempfile, slavetempfile, octoprintmarker):
        for line in mastertempfile:
            totaloutput.append(line)
        totaloutput.append(octoprintmarker)
        for line in slavetempfile:
            totaloutput.append(line)


    def toolchangetestermaster():
        toolchangetestmaster.append(startscriptMaster)
        toolchangetestmaster.append(toolchangeMasterRight)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterLeft)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(layerchangeMaster)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterRight)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterLeft)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(layerchangeMaster)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterRight)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterLeft)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(layerchangeMaster)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterRight)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterLeft)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(layerchangeMaster)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterRight)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterLeft)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(layerchangeMaster)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterRight)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(toolchangeMasterLeft)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(layerchangeMaster)
        toolchangetestmaster.append("G4 S5\n")
        toolchangetestmaster.append(endscriptMaster)


    def toolchangetesterslave():
        toolchangetestslave.append(startscriptSlave)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveRight)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveLeft)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(layerchangeSlave)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveRight)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveLeft)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(layerchangeSlave)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveRight)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveLeft)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(layerchangeSlave)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveRight)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveLeft)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(layerchangeSlave)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveRight)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveLeft)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(layerchangeSlave)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveRight)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(toolchangeSlaveLeft)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(layerchangeSlave)
        toolchangetestslave.append("G4 S5\n")
        toolchangetestslave.append(endscriptSlave)


    ## Main starts here

    ## Refer to concept flowchart for the dev version architecture. Last updated november 2017

    starttime = time.time()
    # filereader()                                    # Read file, only needed for standalone
    timefilereader = time.time()
    print("File read completed! Time to read file: " + str(timefilereader - starttime) + " Total time elapsed: " + str(
        timefilereader - starttime))

    # temporarily switched off, should be toggle with a varaible gcode relative = true/false
    # relativeE(filereader.totalgcode)                 # Make E relative
    timeminmax = time.time()
    # print("Minimum and maximum X and Y extracted! Time to set relative E: "+str(timeminmax - timefilereader)+ " Total time elapsed: " + str(timeminmax-starttime))
    # layers = fetchlayer(filereader.totalgcode)        # Extract layers from standalone import
    layers = data  # Extract layers as supplied by cura

    timelayers = time.time()
    print("Layers extracted! Time to extractlayers: " + str(timelayers - timeminmax) + " Total time elapsed: " + str(
        timelayers - starttime))
    minX, maxX, minY, maxY = minmax(layers[1])  # Note: layers[0] contains Cura start data, the first layer is contained in layers[1]
    layerproperties(minX, maxX, externalxcurrent)  # Determine layer properties and toolchangescripts for first layer
    mastertempfile.append(startscriptMaster)  # Add startscript for master
    slavetempfile.append(startscriptSlave)  # Add startscript for slave
    count = 0  # Keep track of processed layers for debugging

    # Process each layer using distributor and recombinelayer functions for each layer
    for layer in layers[1:]:
        minX, maxX, minY, maxY = minmax(layer)  # Find measurements for this layer
        layerproperties(minX, maxX, externalxcurrent)  # Determine layer properties and toolchangescripts for this layer
        layernumber = layers.index(layer)
        distributor(layer)  # Distribute layer
        print("Distributor layer " + str(count) + " complete!")
        count += 1

        if layers.index(layer) >= 1:
            recombinelayer(sublayer_a, sublayer_b, sublayer_c, sublayer_d)

        # Add nonexistant, not-executed command for search functionalities to default to
        sublayer_a = ["G968 X0 Y0 E0 ; Sublayer A, needed for postprocessor \n"]
        sublayer_b = ["G968 X0 Y0 E0 ; Sublayer B, needed for postprocessor \n"]
        sublayer_c = ["G968 X0 Y0 E0 ; Sublayer C, needed for postprocessor \n"]
        sublayer_d = ["G968 X0 Y0 E0 ; Sublayer D, needed for postprocessor \n"]
    timedistributor = time.time()
    print(
    "Distributor complete! Time to distibute lines: " + str(timedistributor - timelayers) + " Total time elapsed: " + str(
        timedistributor - starttime))

    mastertempfile.append(endscriptMaster)  # Add endscripts
    slavetempfile.append(endscriptSlave)

    combinemasterslave(mastertempfile, slavetempfile, octoprintmarker)  # Combine master and slave tempfiles

    toolchangetestmaster = []
    toolchangetestslave = []
    # -- Uncomment this section to output toolchanger testfiles --
    # toolchangetestermaster()
    # toolchangetesterslave()
    # filewriter(toolchangetestmaster, "debugtoolchangemaster")
    # filewriter(toolchangetestslave, "debugtoolchangeslave")

	#temp of for plugin
    #filewriter(mastertempfile, str(filetoread) + "_master")
    #filewriter(slavetempfile, str(filetoread) + "_slave")

    timeend = time.time()
    print("File write complete! Time to write file: " + str(timeend - timedistributor) + " Total time elapsed: " + str(
        timeend - starttime))
    data = totaloutput

    return data
