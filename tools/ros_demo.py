import argparse
import glob
from pathlib import Path
import time
import copy
import json
import os

# VISUALIZATION TOOLS
from visual_utils import ros_vis_utils as V
ROS_DEBUG_FLAG = True

import numpy as np
import torch

# LOCAL IMPORTS
from pcdet.config import cfg, cfg_from_yaml_file
from pcdet.datasets import DatasetTemplate
from pcdet.models import build_network, load_data_to_gpu
from pcdet.utils import common_utils
from pcdet.datasets.coda import coda_utils

# ROS IMPORTS
import rospy
from sensor_msgs.msg import PointCloud2
from sensor_msgs import point_cloud2
from visualization_msgs.msg import Marker, MarkerArray

from pyquaternion import Quaternion

from demo import DemoDataset

from queue import Queue

pc_msg_queue = Queue()

def normalize_color(color):
    normalized_color = [(r / 255, g / 255, b / 255) for r, g, b in color]
    return normalized_color

def parse_config():
    parser = argparse.ArgumentParser(description='arg parser')
    parser.add_argument('--cfg_file', type=str, default='tools/cfgs/da-coda-coda_models/waymocenterhead/pvrcnn_allclass32full_finetune_headfull.yaml',
                        help='specify the config for demo')
    parser.add_argument('--pc', '--point_cloud_topic', type=str, default='/coda/ouster/points',
                        help='specify the point cloud ros topic name')
    parser.add_argument('--ckpt', type=str, default='ckpts/coda128_allclass_bestoracle.pth', help='specify the pretrained model')

    args = parser.parse_args()

    cfg_from_yaml_file(args.cfg_file, cfg)

    return args, cfg

def point_cloud_callback(msg):
    if ROS_DEBUG_FLAG:
        pc_data = point_cloud2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)
        pc_list = list(pc_data)
        pc_np = np.array(pc_list, dtype=np.float32)

        print("Received point cloud with shape ", pc_np.shape)

    pc_msg_queue.put(msg)



def main():
    args, cfg = parse_config()
    logger = common_utils.create_logger()
    logger.info('-----------------ROS Demo of OpenPCDet-------------------------')

    #1 Fill in dummy dataset to set point features values
    dummy_dataset = DemoDataset(
        dataset_cfg=cfg.DATA_CONFIG, class_names=cfg.CLASS_NAMES, training=False,
        root_path=Path("../data"), ext=".bin", logger=logger
    )
    color_map=normalize_color(coda_utils.BBOX_ID_TO_COLOR)

    #2 Load model
    model = build_network(model_cfg=cfg.MODEL, num_class=len(cfg.CLASS_NAMES), dataset=dummy_dataset)
    model.load_params_from_file(filename=args.ckpt, logger=logger, to_cpu=True)
    model.cuda()
    model.eval()

    def point_cloud_callback_new(msg):
        pc_data = point_cloud2.read_points(msg, field_names=("x", "y", "z"), skip_nans=True)
        pc_list = list(pc_data)
        pc_np = np.array(pc_list, dtype=np.float32)

        # Rotate point cloud to match camera frame
        quaternion = Quaternion(x=-0.015, y=0.197, z=0.003, w=0.980)
        pc_np = np.dot(pc_np, quaternion.rotation_matrix.T)

        
        msg = point_cloud2.create_cloud_xyz32(msg.header, pc_np)



        print("Received point cloud with shape ", pc_np.shape)
        pointcloud_pub.publish(msg)
        V.visualize_3d(model, dummy_dataset, msg, bbox_3d_pub, color_map, logger)



    #3 Initialize ROS
    pc_topic = args.pc
    rospy.init_node('CODaROSDetector', anonymous=True)
    rospy.Subscriber(pc_topic, PointCloud2, point_cloud_callback_new, queue_size=1)
    
    bbox_3d_pub = rospy.Publisher('/coda/bbox_3d', MarkerArray, queue_size=10)
    pointcloud_pub = rospy.Publisher('/coda/points', PointCloud2, queue_size=10)

    #4 Load dummy data to speed up first pass
    dummy_pc = np.random.rand(1000, 3).astype(np.float32)
    dummy_data_dict = V.pcnp_to_datadict(dummy_pc, dummy_dataset, frame_id=0)
    pred_dicts, _ = model.forward(dummy_data_dict)
    
    logger.info("Model initalized...")
    while not rospy.is_shutdown():
        rospy.spin()
    
    #     if not pc_msg_queue.empty():
    #         pc_msg = pc_msg_queue.get()
            
    #         V.visualize_3d(model, dummy_dataset, pc_msg, bbox_3d_pub, color_map, logger)
    logger.info("Demo complete, cleaning up...")

if __name__ == '__main__':
    main()