from __future__ import print_function
from collections import deque
import rospy
import rosparam
import sys
from os.path import isdir, exists
import rospkg
import numpy as np

from senseglove_shared_resources.msg import FingerDistanceFloats

class Calibration:

    def __init__(self, glove_nr=1, name="default"):
        self.glove_nr = glove_nr
        self.name = name  # Calibration profile name

        # Defaults
        self.pinch_calibration_min = [0.0, 0.0, 0.0]  # [index, middle, ring][x, y, z] random values from Kees
        self.pinch_calibration_max = [0.0, 0.0, 0.0]  # [index, middle, ring]

        self.avg_open_flat = [0.0, 0.0, 0.0]  # distances between thumb&index thumb&middle thumb&ring
        self.avg_thumb_index_pinch = [0.0, 0.0, 0.0]
        self.avg_thumb_middle_pinch = [0.0, 0.0, 0.0]
        self.avg_thumb_ring_pinch = [0.0, 0.0, 0.0]

        self.finished_open_flat = False
        self.finished_thumb_index_pinch = False
        self.finished_thumb_middle_pinch = False
        self.finished_thumb_ring_pinch = False

        self.calib_time = 2  # sec

        self.databuffer = deque(maxlen=10)

    def set_open_flat(self, avg_positions_msg):
        """
        Call when user holds a flat hand
        """
        for i, position in enumerate([avg_positions_msg.index, avg_positions_msg.middle, avg_positions_msg.ring]):
            self.avg_open_flat = [position.x, position.y, position.z]

        self.finished_open_flat = True

    def set_thumb_index_pinch(self, avg_positions_msg):
        """
        Call when user pinches index finger and thumb
        """
        if not self.finished_open_flat:
            print("First calibrate the flat hand, then the pinching position!")
            return

        self.avg_thumb_index_pinch = [avg_positions_msg.th_ff, avg_positions_msg.th_mf, avg_positions_msg.th_rf]
        if self.avg_thumb_index_pinch == self.avg_open_flat:
            rospy.logwarn("Identical measurements! Cannot calibrate. Is your glove still connected?")
            return

        self.finished_thumb_index_pinch = True

    def set_thumb_middle_pinch(self, avg_positions_msg):
        """
        Call when user pinches middle finger and thumb
        """
        if not self.finished_open_flat:
            print("First calibrate the flat hand, then the pinching position!")
            return

        self.avg_thumb_middle_pinch = [avg_positions_msg.th_ff, avg_positions_msg.th_mf, avg_positions_msg.th_rf]
        if self.avg_thumb_middle_pinch == self.avg_open_flat:
            rospy.logwarn("Identical measurements! Cannot calibrate. Is your glove still connected?")
            return

        self.finished_thumb_middle_pinch = True

    def set_thumb_ring_pinch(self, avg_positions_msg):
        """
        Call when user pinches ring finger and thumb
        """
        if not self.finished_open_flat:
            print("First calibrate the flat hand, then the pinching position!")
            return

        self.avg_thumb_ring_pinch = [avg_positions_msg.th_ff, avg_positions_msg.th_mf, avg_positions_msg.th_rf]
        if self.avg_thumb_ring_pinch == self.avg_open_flat:
            rospy.logwarn("Identical measurements! Cannot calibrate. Is your glove still connected?")
            return

        self.finished_thumb_ring_pinch = True

    def is_calibrated(self):
        return self.finished_open_flat and self.finished_thumb_index_pinch and self.finished_thumb_middle_pinch and self.finished_thumb_ring_pinch

    def run_interactive_calibration(self):
        """
        Run an interactive (CLI) session for calibration.
        """

        rospy.Subscriber('senseglove_' + str(self.glove_nr) + '/finger_distances', FingerDistanceFloats, callback=self.senseglove_callback)

        rospy.loginfo("Calibration of senseglove started, please flatten your hand.")
        rospy.loginfo("Type [y] + [Enter] when ready, or [q] + [Enter] to quit.")

        self.key_press_interface()
        self.log_finger_distances()

        # Set average values for flat hand
        self.set_open_flat(self.get_avg_finger_distances())

        rospy.loginfo("Step 1 done.")

        rospy.loginfo("Calibration step 2, please pinch with your index finger and thumb.")
        rospy.loginfo("Type [y] + [Enter] when ready, or [q] + [Enter] to quit.")

        self.key_press_interface()
        self.log_finger_distances()

        # Set average values for pinch between thumb and index finger
        self.set_thumb_index_pinch(self.get_avg_finger_distances())
        if not self.finished_thumb_index_pinch:
            rospy.logerr("Could not finish thumb to index pinch calibration, calibration failed")
            return False

        rospy.loginfo("Step 2 done")

        rospy.loginfo("Calibration step 3, please pinch with your middle finger and thumb.")
        rospy.loginfo("Type [y] + [Enter] when ready, or [q] + [Enter] to quit.")

        self.key_press_interface()
        self.log_finger_distances()

        # Set average values for pinch between thumb and middle finger
        self.set_thumb_middle_pinch(self.get_avg_finger_distances())
        if not self.finished_thumb_middle_pinch:
            rospy.logerr("Could not finish thumb to middle pinch calibration, calibration failed")
            return False

        rospy.loginfo("Step 3 done")

        rospy.loginfo("Calibration step 4, please pinch with your ring finger and thumb.")
        rospy.loginfo("Type [y] + [Enter] when ready, or [q] + [Enter] to quit.")

        self.key_press_interface()
        self.log_finger_distances()

        # Set average values for pinch between thumb and ring finger
        self.set_thumb_ring_pinch(self.get_avg_finger_distances())
        if not self.finished_thumb_ring_pinch:
            rospy.logerr("Could not finish thumb to index pinch calibration, calibration failed")
            return False

        rospy.loginfo("Step 4 (Final step) done")

        rospy.loginfo("Computing calibration parameters...")

        """
        Calibration data:
        - pinch minimum: The corresponding value when the user pinches their fingers for step 2 until 4
        - pinch maximum: for conveniences sake simply the open flat position. A different maximum value could probably 
        be found, but whatever \_(:/)_/
        """

        # minimum value of the finger distance when pinching with two fingers in three combinations
        self.pinch_calibration_min = [self.avg_thumb_index_pinch[0], self.avg_thumb_middle_pinch[1], self.avg_thumb_ring_pinch[2]]
        # maximum value between fingers and the thumb to find corresponding interpolation data
        self.pinch_calibration_max = self.avg_open_flat
        if self.pinch_calibration_max == 0.0:
            rospy.logwarn("Got max value zero. Is your glove still connected?")
            return False


        rospy.loginfo("The calibration for '%s' is done. These are the numbers:" % self.name)
        rospy.loginfo("Pinch calibration min: %s\n" % self.pinch_calibration_min)
        rospy.loginfo("Pinch calibration max: %s\n" % self.pinch_calibration_max)
        rospy.loginfo("Type [y] + [Enter] when OK, or [q] + [Enter] to discard and quit.")

        self.key_press_interface()

        rospy.loginfo("Calibration successful!")
        rospy.loginfo("Setting on param server and saving to file...")

        # Set parameters
        rospy.set_param('~pinch_calibration_min', self.pinch_calibration_min)
        rospy.set_param('~pinch_calibration_max', self.pinch_calibration_max)
        config_folder = rospkg.RosPack().get_path('senseglove_shared_resources') + "/calib"

        if not isdir(config_folder):
            rospy.logwarn("Could not locate calibration folder %s, not saving." % config_folder)
        else:
            filename = config_folder + "/" + self.name + ".yaml"
            if exists(filename):
                rospy.logwarn("Overwriting %s" % filename)
            rosparam.dump_params(filename, rospy.get_name())
            rospy.loginfo("Done!")

        return True

    def senseglove_callback(self, finger_distance_msg):
        self.databuffer.appendleft(finger_distance_msg)

    def get_avg_finger_distances(self):

        avg_positions_msg = FingerDistanceFloats()

        thumb_indexdata = [x.th_ff for x in self.databuffer]
        if len(thumb_indexdata) == 0:
            rospy.logwarn("No data received! Is your glove still connected?")
        else:
            avg_positions_msg.th_ff = sum(thumb_indexdata) / len(thumb_indexdata)

        thumb_middledata = [x.th_mf for x in self.databuffer]
        if len(thumb_middledata) == 0:
            rospy.logwarn("No data received! Is your glove still connected?")
        else:
            avg_positions_msg.th_mf = sum(thumb_middledata) / len(thumb_middledata)

        thumb_ringdata = [x.th_rf for x in self.databuffer]
        if len(thumb_ringdata) == 0:
            rospy.logwarn("No data received! Is your glove still connected?")
        else:
            avg_positions_msg.th_rf = sum(thumb_ringdata) / len(thumb_ringdata)

        return avg_positions_msg

    def key_press_interface(self):
        k = raw_input()

        while not (k == 'q' or k == 'y'):
            rospy.loginfo("Not valid: %s. Type [y] + [Enter] when ready, or [q] + [Enter] to quit." % k)
            k = raw_input()

        if k == "q":
            rospy.loginfo("Calibration aborted!")
            return False

    def log_finger_distances(self):
        self.databuffer.clear() # Start with a fresh buffer
        for i in range(int(self.calib_time/0.05)):
            print(".", end="")
            sys.stdout.flush()
            rospy.sleep(0.05)
        print()
