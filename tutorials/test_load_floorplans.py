import sys
from os.path import join, abspath, dirname, isdir, isfile
from os import listdir, pardir
RD = abspath(join(dirname(__file__), pardir, pardir))
sys.path.extend([join(RD), join(RD, 'pddlstream'), join(RD, 'pybullet_planning'), join(RD, 'lisdf')])

from pybullet_tools.utils import wait_unlocked, PI, wait_if_gui, set_renderer, set_camera_pose

from problem_sets.problem_utils import create_world
from cogarch_tools.cogarch_utils import get_parser, init_gui

from world_builder.loaders import load_floor_plan
from world_builder.loaders_nvidia_kitchen import FRONT_CAMERA_POINT, DOWNWARD_CAMERA_POINT
from world_builder.robot_builders import build_robot_from_args

from tutorials.test_utils import get_test_world


def test_load_spot_in_office():
    """ have bug now """
    world = get_test_world(robot='spot', semantic_world=True, width=1980, height=1238)
    load_floor_plan(world, plan_name='office_1.svg', DEBUG=True, spaces=None, surfaces=None,
                    RANDOM_INSTANCE=False, verbose=True)
    wait_if_gui()


def test_load_floating_gripper_in_kitchen():
    args = get_parser(config='config_dev.yaml')

    init_gui(args, width=1440, height=1120)
    world = create_world(args)
    robot = build_robot_from_args(world, robot_name='feg', initial_q=[1.5, 7, 0.7, 0, -PI / 2, 0])

    floor = load_floor_plan(world, plan_name='kitchen_v2.svg')
    world.remove_object(floor)
    set_camera_pose((2, 7, 2), (0, 7, 0.5))
    wait_if_gui()


if __name__ == '__main__':
    test_load_floating_gripper_in_kitchen()
