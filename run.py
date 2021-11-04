# Networking and Logging
import logging
import logging.handlers
import os
import socket

logging.basicConfig(level=logging.DEBUG)

# General imports
import hashlib
import threading
import time
import inspect

# Robot Imports
import sys 
sys.path.append('/home/pi/robotkit')
sys.path.append('/home/pi/robotcode') 

from robot import MyRobot # should be in robotcode
import pikitlib # should be in robotkit

# wpilib imports
from networktables import NetworkTables

class main():
    def __init__(self):
        self.r = MyRobot()
        self.current_mode = ""
        self.disabled = True
        
        self.timer = pikitlib.Timer()
        self.connectedIP = None
        self.isRunning = False

    def start(self):
        self.isRunning = True
        self.r.robotInit()
        self.setupBatteryLogger()
        time.sleep(0.1)
        
        # self.status_nt.putBoolean("Code", True) # why?
        # self.checksum = self.getChecksumOfDir("/home/pi/RobotKitLib/RobotRunner/RobotCode/") # why?
        # self.status_nt.putStringArray("Checksum", self.checksum) # why?

        self.stop_threads = False
        self.rl = threading.Thread(target = self.robotLoop, args =(lambda : self.stop_threads, ))
        self.rl.start() 

        self.setupLogging()
        logging.debug("Starting")
        if self.rl.is_alive():
            logging.debug("Main thread created")

    def robotLoop(self, stop):
        bT = pikitlib.Timer() 
        bT.start()

        while not stop():
            
            if bT.get() > 0.2: # so this timer is just to send battery data?
                self.sendBatteryData()
                bT.reset()

            if not self.disabled:

                self.timer.start()
                try:
                    if self.current_mode == "Auton":
                        self.auton()
                    elif self.current_mode == "Teleop":
                        self.teleop()
                except Exception as e:
                    self.catchErrorAndLog(e)
                    break

                self.timer.stop()
                ts = 0.02 - self.timer.get() # why is this so convoluted?
                self.timer.reset()

                if ts < -0.5: # so... took 
                    logging.critical("Program taking too long!")
                    self.quit()
                elif ts < 0:
                    logging.warning("%s has slipped by %s miliseconds!", self.current_mode, ts * -1000)
                else:        
                    time.sleep(ts)
            
            else:
                self.disable() # why?

        self.disable()
            
    def quit(self):
        logging.info("Quitting...")
        self.stop_threads = True
        self.rl.join() 
        self.disable()
        sys.exit()

    def setupMode(self, m):
        """
        Run the init function for the current mode
        """
        
        #if m == "Teleop":
        #    self.r.teleopInit()
        #elif m == "Auton":
        #    self.r.autonomousInit()

        self.current_mode = m

    def auton(self):
        self.r.autonomousPeriodic()

    def teleop(self):
        self.r.teleopPeriodic()
        
    def disable(self):
        m1 = pikitlib.SpeedController(1)
        m2 = pikitlib.SpeedController(2)
        m3 = pikitlib.SpeedController(3)
        m4 = pikitlib.SpeedController(4)
        m = pikitlib.SpeedControllerGroup(m1,m2,m3,m4)
        m.set(0)

    def initMode(self, m):
        # Initializes current mode
        if m == "Teleop":
            self.r.teleopInit()
        elif m == "Auton":
            self.r.autonomousInit()

    #### NetworkTables stuff ######        
    def connect(self):
        """
        Connect to robot NetworkTables server
        """
        NetworkTables.initialize()
        NetworkTables.addConnectionListener(self.connectionListener, immediateNotify=True)

    def connectionListener(self, connected, info):
        """
        Setup the listener to detect any changes to the robotmode table
        """
        self.connectedIP = str(info.remote_ip)
        logging.info("%s; Connected=%s", info, connected)
        sd = NetworkTables.getTable("RobotMode")
        self.status_nt = NetworkTables.getTable("Status")
        sd.addEntryListener(self.valueChanged)
   
    def valueChanged(self, table, key, value, isNew):
        """
        Check for new changes and use them
        """
        #print("valueChanged: key: '%s'; value: %s; isNew: %s" % (key, value, isNew))
        if(key == "Mode"):
            self.setupMode(value)

        if(key == "Disabled"):
            self.disabled = value
            if not value:
                self.initMode(self.current_mode)

        if(key == "ESTOP"):
            self.quit()

    #### end NetworkTables stuff ######        

    # do we really need network logging. Perhaps we do.
    def setupLogging(self):
        rootLogger = logging.getLogger('')
        rootLogger.setLevel(logging.DEBUG)
        socketHandler = logging.handlers.SocketHandler(self.connectedIP,logging.handlers.DEFAULT_TCP_LOGGING_PORT)
        
        rootLogger.addHandler(socketHandler)
    
    def broadcastNoCode(self):
        self.status_nt.putBoolean("Code", False)

    def setupBatteryLogger(self):
        self.battery_nt = NetworkTables.getTable('Battery')
        self.ai = pikitlib.analogInput(2)

    def sendBatteryData(self):
        self.battery_nt.putNumber("Voltage", self.ai.getVoltage() * 3)

    def catchErrorAndLog(self, err, logErr=True):
        if logErr:
            logging.critical("Competition robot should not quit, but yours did!")
            logging.critical(err)
        
        try:
            self.broadcastNoCode()
        except AttributeError:
            #if there is no code, broadcasting wont work
            #TODO: rework how broadcasting works so this isnt required 
            pass

        #logging.critical("Resetting ()...")
        sys.exit()
            
    def debug(self):
        self.disabled = False
        self.start()
        self.setupMode("Teleop")

    # Eli's deployment magic
    # probably don't need this        
    def tryToSetupCode(self):
        try:
            sys.path.insert(1, 'RobotCode')   
            import robot
            for item in inspect.getmembers(robot):
                if "class" in str(item[1]):
                    self.r = getattr(robot, item[0])()
                    return True
        except Exception as e:
            logging.critical("Looks like you dont have any code!")
            logging.critical("Send code with 'python robot.py --action deploy --ip_addr IP'")
            self.catchErrorAndLog(e, False)
            return False
            # pretty sure we don't need this   
   
    def md5(self, fname):
        hash_md5 = hashlib.md5()
        with open(fname, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def getChecksumOfDir(self, path):
        checksums = []
        for filename in os.listdir(path):
            if os.path.isfile(path + filename):
                checksums.append(self.md5(path + filename))
        return sorted(checksums)


logging.debug("hello1")
print("hello2")

m = main()
m.connect()
m.start()

