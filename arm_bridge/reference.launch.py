"""Planning-only MoveIt server; joint playback is synthetic, no controller or SDK."""
from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch.conditions import IfCondition
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    config=(MoveItConfigsBuilder('moveit_resources_panda')
            .robot_description(file_path='config/panda.urdf.xacro')
            .robot_description_semantic(file_path='config/panda.srdf')
            .planning_pipelines(pipelines=['ompl']).to_moveit_configs())
    # Fixed base for the tabletop reference cell.
    config.robot_description_semantic['robot_description_semantic']=config.robot_description_semantic['robot_description_semantic'].replace('type="floating"','type="fixed"')
    config.planning_pipelines['ompl']['path_tolerance']=.001
    config.planning_pipelines['ompl']['panda_arm']['longest_valid_segment_fraction']=.001
    return LaunchDescription([
        DeclareLaunchArgument('rviz',default_value='true'),
        Node(package='tf2_ros',executable='static_transform_publisher',arguments=['0','0','0','0','0','0','world','panda_link0']),
        Node(package='robot_state_publisher',executable='robot_state_publisher',parameters=[config.robot_description]),
        Node(package='moveit_ros_move_group',executable='move_group',parameters=[config.to_dict(),{'allow_trajectory_execution':False,'publish_robot_description_semantic':True}],output='screen'),
        Node(package='rviz2',executable='rviz2',arguments=['-d',str(Path(__file__).with_name('reference.rviz'))],parameters=[config.robot_description],condition=IfCondition(LaunchConfiguration('rviz'))),
    ])
