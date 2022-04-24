#!/usr/bin/env python
import sys
import threading
import time

import cv2 as cv
import numpy as np
import rospy
from detectron2.config import get_cfg
from detectron2.data import MetadataCatalog
from cv_bridge import CvBridge, CvBridgeError
# import some common detectron2 utilities
from detectron2.engine import DefaultPredictor
from detectron2.utils.logger import setup_logger
from detectron2.utils.visualizer import Visualizer
from mask2former.msg import Result
from sensor_msgs.msg import Image, RegionOfInterest

from detectron2.projects.deeplab import add_deeplab_config
from mask2former_library import add_maskformer2_config
from visualization.predictor import VisualizationDemo

#To-Do import distort coefficients from camera info topic


class Detectron2node(object):
    def __init__(self):
        rospy.logwarn("Initializing")
        setup_logger()

        self._bridge = CvBridge()
        self._last_msg = None
        self._msg_lock = threading.Lock()
        self._image_counter = 0

        self.cfg = get_cfg()
        add_deeplab_config(self.cfg)
        add_maskformer2_config(self.cfg)

        try:
            self.cfg.merge_from_file('/home/appuser/mask2former_ws/model_config.yaml')
            self.cfg.MODEL.WEIGHTS = '/home/appuser/mask2former_ws/model_weights.pkl'
        except:
            self.cfg.merge_from_file('/home/niklas/catkin_ws/model_config.yaml')
            self.cfg.MODEL.WEIGHTS = '/home/niklas/catkin_ws/model_weights.pkl'

        #self.predictor = DefaultPredictor(self.cfg)
        
        
        self._class_names = MetadataCatalog.get("coco_2017_val_panoptic")

        self._visualization = self.load_param('~visualization',True)
        self._result_pub = rospy.Publisher('objects', Result, queue_size=1)
        self._vis_pub = rospy.Publisher('result_images', Image, queue_size=1)
        self._sub = rospy.Subscriber('camera_0/image', Image , self.callback_image, queue_size=1)
        self.start_time = time.time()
        rospy.logwarn("Initialized")

    def run(self):

        rate = rospy.Rate(100)
        while not rospy.is_shutdown():
            if self._msg_lock.acquire(False):
                img_msg = self._last_msg
                self._last_msg = None
                self._msg_lock.release()
            else:
                rate.sleep()
                continue

            if img_msg is not None:
                self._image_counter = self._image_counter + 1
                if (self._image_counter % 11) == 10:
                    rospy.loginfo("Images detected per second=%.2f",
                                  float(self._image_counter) / (time.time() - self.start_time))

                np_image = self.convert_to_cv_image(img_msg)

                CAMERA_0_K = [1125.74141,    0.,  917.19798,
                              0., 1124.54648,  533.19051,
                              0.,    0.,    1.]
                CAMERA_0_D = [-0.164614, 0.004523, -0.010740, -0.000858, 0.042291, 0.358953, -0.192945, 0.076769]


                
                camera_matrix = np.array(CAMERA_0_K, np.float32).reshape((3, 3))
                distortion_coeffs = np.array(CAMERA_0_D, np.float32)
                rectified_img = cv.undistort(np_image, camera_matrix, distortion_coeffs)

                demo = VisualizationDemo(self.cfg)
                predictions, visualized_output = demo.run_on_image(rectified_img)
                #rospy.loginfo(predictions)
                rospy.loginfo(type(visualized_output))
                # Visualize results
                image_msg = self._bridge.cv2_to_imgmsg(visualized_output.get_image(), encoding="rgb8")
                self._vis_pub.publish(image_msg)

            rate.sleep()

    def getResult(self, predictions):

        boxes = predictions.pred_boxes if predictions.has("pred_boxes") else None

        if predictions.has("pred_masks"):
            masks = np.asarray(predictions.pred_masks)
        else:
            return

        result_msg = Result()
        result_msg.header = self._header
        result_msg.class_ids = predictions.pred_classes if predictions.has("pred_classes") else None
        
        #testing purposes only
        #result_msg.class_names = np.array(self._class_names)[result_msg.class_ids.numpy()]
        result_msg.scores = predictions.scores if predictions.has("scores") else None

        for i, (x1, y1, x2, y2) in enumerate(boxes):
            mask = np.zeros(masks[i].shape, dtype="uint8")
            mask[masks[i, :, :]]=255
            mask = self._bridge.cv2_to_imgmsg(mask)
            result_msg.masks.append(mask)

            box = RegionOfInterest()
            box.x_offset = np.uint32(x1)
            box.y_offset = np.uint32(y1)
            box.height = np.uint32(y2 - y1)
            box.width = np.uint32(x2 - x1)
            result_msg.boxes.append(box)

        return result_msg

    def convert_to_cv_image(self, image_msg):

        if image_msg is None:
            return None

        self._width = image_msg.width
        self._height = image_msg.height
        channels = int(len(image_msg.data) / (self._width * self._height))

        encoding = None
        if image_msg.encoding.lower() in ['rgb8', 'bgr8']:
            encoding = np.uint8
        elif image_msg.encoding.lower() == 'mono8':
            encoding = np.uint8
        elif image_msg.encoding.lower() == '32fc1':
            encoding = np.float32
            channels = 1

        cv_img = np.ndarray(shape=(image_msg.height, image_msg.width, channels),
                            dtype=encoding, buffer=image_msg.data)

        if image_msg.encoding.lower() == 'mono8':
            cv_img = cv.cvtColor(cv_img, cv.COLOR_RGB2GRAY)
        else:
            cv_img = cv.cvtColor(cv_img, cv.COLOR_RGB2BGR)

        return cv_img

    def callback_image(self, msg):
        rospy.logdebug("Get an image")
        if self._msg_lock.acquire(False):
            self._last_msg = msg
            self._header = msg.header
            self._msg_lock.release()        

    @staticmethod
    def load_param(param, default=None):
        new_param = rospy.get_param(param, default)
        rospy.loginfo("[Detectron2] %s: %s", param, new_param)
        return new_param

def main(argv):
    rospy.init_node('visualization_node')
    node = Detectron2node()
    node.run()

if __name__ == '__main__':
    main(sys.argv)
