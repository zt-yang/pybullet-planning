import random

import numpy as np
from itertools import product
from math import radians as rad

from .utils import create_box, set_base_values, set_point, set_pose, get_pose, \
    get_bodies, z_rotation, load_model, load_pybullet, HideOutput, create_body, assign_link_colors, \
    get_box_geometry, get_cylinder_geometry, create_shape_array, unit_pose, Pose, \
    Point, LockRenderer, FLOOR_URDF, TABLE_URDF, add_data_path, TAN, set_color, BASE_LINK, remove_body,\
    add_data_path, connect, dump_body, disconnect, wait_for_user, get_movable_joints, get_sample_fn, \
    set_joint_positions, get_joint_name, LockRenderer, link_from_name, get_link_pose, \
    multiply, Pose, Point, interpolate_poses, HideOutput, draw_pose, set_camera_pose, load_pybullet, \
    assign_link_colors, add_line, point_from_pose, remove_handles, BLUE, INF, create_shape, \
    approximate_as_prism, set_renderer

from pybullet_tools.pr2_primitives import Conf, Grasp
from .pr2_utils import DRAKE_PR2_URDF

from .ikfast.utils import IKFastInfo
from .ikfast.ikfast import * # For legacy purposes

FE_GRIPPER_URDF = "models/franka_description/robots/hand_se3.urdf"
#FRANKA_URDF = "models/franka_description/robots/panda_arm.urdf"
FRANKA_URDF = "models/franka_description/robots/panda_arm_hand.urdf"

PANDA_INFO = IKFastInfo(module_name='franka_panda.ikfast_panda_arm', base_link='panda_link0',
                        ee_link='panda_link8', free_joints=['panda_joint7'])

BASE_VELOCITIES = np.array([1., 1., 1, rad(180), rad(180), rad(180)]) / 1.
BASE_RESOLUTIONS = np.array([0.05, 0.05, 0.05, rad(10), rad(10), rad(10)])

ARM_NAME = 'hand'
TOOL_LINK = 'panda_hand'
CACHE = {}

class Problem():
    def __init__(self, robot, obstacles):
        self.robot = robot
        self.fixed = obstacles

def create_franka():
    with LockRenderer():
        with HideOutput(True):
            robot = load_model(FRANKA_URDF, fixed_base=True)
            assign_link_colors(robot, max_colors=3, s=0.5, v=1.)
            # set_all_color(robot, GREEN)
    return robot

def create_fe_gripper(init_q=None):
    with LockRenderer():
        with HideOutput(True):
            robot = load_model(FE_GRIPPER_URDF, fixed_base=False)
            set_gripper_positions(robot, w=0.08)
            if init_q != None:
                set_se3_conf(robot, init_q)
            # assign_link_colors(robot, max_colors=3, s=0.5, v=1.)
            # set_all_color(robot, GREEN)
    return robot

#####################################################################

def test_retraction(robot, info, tool_link, distance=0.1, **kwargs):
    ik_joints = get_ik_joints(robot, info, tool_link)
    start_pose = get_link_pose(robot, tool_link)
    end_pose = multiply(start_pose, Pose(Point(z=-distance)))
    handles = [add_line(point_from_pose(start_pose), point_from_pose(end_pose), color=BLUE)]
    #handles.extend(draw_pose(start_pose))
    #hand®les.extend(draw_pose(end_pose))
    path = []
    pose_path = list(interpolate_poses(start_pose, end_pose, pos_step_size=0.01))
    for i, pose in enumerate(pose_path):
        print('Waypoint: {}/{}'.format(i+1, len(pose_path)))
        handles.extend(draw_pose(pose))
        conf = next(either_inverse_kinematics(robot, info, tool_link, pose, **kwargs), None)
        if conf is None:
            print('Failure!')
            path = None
            wait_for_user()
            break
        set_joint_positions(robot, ik_joints, conf)
        path.append(conf)
        wait_for_user()
        # for conf in islice(ikfast_inverse_kinematics(robot, info, tool_link, pose, max_attempts=INF, max_distance=0.5), 1):
        #    set_joint_positions(robot, joints[:len(conf)], conf)
        #    wait_for_user()
    remove_handles(handles)
    return path

def test_ik(robot, info, tool_link, tool_pose):
    draw_pose(tool_pose)
    # TODO: sort by one joint angle
    # TODO: prune based on proximity
    ik_joints = get_ik_joints(robot, info, tool_link)
    for conf in either_inverse_kinematics(robot, info, tool_link, tool_pose, use_pybullet=False,
                                          max_distance=INF, max_time=10, max_candidates=INF):
        # TODO: profile
        set_joint_positions(robot, ik_joints, conf)
        wait_for_user()

def sample_ik_tests(robot):
    joints = get_movable_joints(robot)
    tool_link = link_from_name(robot, TOOL_LINK)

    info = PANDA_INFO
    check_ik_solver(info)

    sample_fn = get_sample_fn(robot, joints)
    for i in range(10):
        print('Iteration:', i)
        conf = sample_fn()
        set_joint_positions(robot, joints, conf)
        wait_for_user()
        # test_ik(robot, info, tool_link, get_link_pose(robot, tool_link))
        test_retraction(robot, info, tool_link, use_pybullet=False,
                        max_distance=0.1, max_time=0.05, max_candidates=100)

######################################################

from pybullet_tools.utils import plan_joint_motion, create_flying_body, SE3, euler_from_quat, BodySaver, \
    intrinsic_euler_from_quat, quat_from_euler, wait_for_duration, get_aabb, get_aabb_extent, \
    joint_from_name
from pybullet_tools.pr2_primitives import Trajectory, Commands, State

SE3_GROUP = ['x', 'y', 'z', 'roll', 'pitch', 'yaw']
FINGERS_GROUP = ['panda_finger_joint1', 'panda_finger_joint2']
BASE_LINK = 'world_link'

def set_gripper_positions(robot, w=0.0):
    joints = get_joints_by_group(robot, FINGERS_GROUP)
    set_joint_positions(robot, joints, [w/2, w/2])

def open_gripper(robot):
    set_gripper_positions(robot, w=0.08)

def open_cloned_gripper(robot, gripper, w = 0.12): ## 0.08 is the limit
    """ because link and joint names aren't cloned """
    joints = get_joints_by_group(robot, FINGERS_GROUP)
    w = min(w, 0.12)
    set_joint_positions(gripper, joints, [w / 2, w / 2])

def close_cloned_gripper(robot, gripper):
    """ because link and joint names aren't cloned """
    joints = get_joints_by_group(robot, FINGERS_GROUP)
    set_joint_positions(gripper, joints, [0, 0])

def set_cloned_se3_conf(robot, gripper, conf):
    joints = get_joints_by_group(robot, SE3_GROUP)
    return set_joint_positions(gripper, joints, conf)

def get_cloned_se3_conf(robot, gripper):
    joints = get_joints_by_group(robot, SE3_GROUP)
    return get_joint_positions(gripper, joints)

def get_cloned_hand_pose(robot, gripper):
    link = link_from_name(robot, TOOL_LINK)
    return get_link_pose(gripper, link)

def get_hand_pose(robot):
    link = link_from_name(robot, TOOL_LINK)
    return get_link_pose(robot, link)

def set_se3_conf(robot, se3):
    set_joint_positions(robot, get_se3_joints(robot), se3)
    # pose = pose_from_se3(se3)
    # set_pose(robot, pose)

def get_joints_by_group(robot, group):
    return [joint_from_name(robot, j) for j in group]

def get_se3_joints(robot):
    return get_joints_by_group(robot, SE3_GROUP)

def get_se3_conf(robot):
    return get_joint_positions(robot, get_se3_joints(robot))
    # pose = get_pose(robot)
    # return se3_from_pose(pose)

# def pose_to_se3(p):
#     # return list(p[0]) + list(euler_from_quat(p[1]))
#     print('\n\n franka_utils.pose_to_se3 | deprecated! \n\n')
#     return np.concatenate([np.asarray(p[0]), np.asarray(euler_from_quat(p[1]))])
#
# def se3_to_pose(conf):
#     print('\n\n franka_utils.se3_to_pose | deprecated! \n\n')
#     return (conf[:3], quat_from_euler(conf[3:]))

def se3_from_pose(p):
    print('Deprecated se3_from_pose, please use se3_ik()')
    return list(np.concatenate([np.asarray(p[0]), np.asarray(euler_from_quat(p[1]))]))

def pose_from_se3(conf):
    # print('Deprecated pose_from_se3, please use se3_fk()')
    return (conf[:3], quat_from_euler(conf[3:]))

from pybullet_tools.utils import irange, is_pose_close, CLIENT
import pybullet as p

def se3_ik(robot, target_pose, max_iterations=2000, max_time=5, verbose=False):
    report_failure = True
    title = f'   se3_ik | for pose {nice(target_pose)}'
    if nice(target_pose) in CACHE:
        if verbose: print(f'{title} found in cache')
        return CACHE[nice(target_pose)]
    start_time = time.time()
    link = link_from_name(robot, TOOL_LINK)
    target_point, target_quat = target_pose
    sub_joints = get_se3_joints(robot)
    sub_robot = robot.create_gripper()  ## color=BLUE ## for debugging
    for iteration in irange(max_iterations):
        if elapsed_time(start_time) >= max_time:
            remove_body(sub_robot)
            if verbose or report_failure: print(f'{title} failed after {max_time} sec')
            return None
        sub_kinematic_conf = p.calculateInverseKinematics(sub_robot, link, target_point, target_quat, physicsClientId=CLIENT)
        sub_kinematic_conf = sub_kinematic_conf[:-2] ##[3:-2]
        set_joint_positions(sub_robot, sub_joints, sub_kinematic_conf)
        if is_pose_close(get_link_pose(sub_robot, link), target_pose):
            if verbose:
                print(f'{title} found after {iteration} trials and '
                    f'{nice(elapsed_time(start_time))} sec', nice(sub_kinematic_conf))
                set_camera_target_body(sub_robot, dx=0.5, dy=0.5, dz=0.5)
            remove_body(sub_robot)
            CACHE[nice(target_pose)] = sub_kinematic_conf
            return sub_kinematic_conf
    if verbose or report_failure: print(f'{title} failed after {max_iterations} iterations')
    return None

def approximate_as_box(robot):
    pose = get_pose(robot)
    set_pose(robot, unit_pose())
    aabb = get_aabb(robot)
    set_pose(robot, pose)
    return get_aabb_extent(aabb)

def plan_se3_motion(robot, initial_conf, final_conf, obstacles=[],
                    custom_limits={}, attachments=[]):
    joints = get_se3_joints(robot)
    set_joint_positions(robot, joints, initial_conf)
    path = plan_joint_motion(robot, joints, final_conf, obstacles=obstacles,
                             weights=[1, 1, 1, 0.2, 0.2, 0.2], smooth=100,
                             attachments=attachments,
                             self_collisions=False, custom_limits=custom_limits)
    return path

def get_free_motion_gen(problem, custom_limits={}, collisions=True, teleport=False,
                        visualize=False, time_step=0.05):
    robot = problem.robot
    saver = BodySaver(robot)
    obstacles = problem.fixed if collisions else []
    def fn(q1, q2, w, fluents=[]):

        saver.restore()
        q1.assign()
        w.assign()
        set_renderer(False)
        raw_path = plan_se3_motion(robot, q1.values, q2.values, obstacles=obstacles,
                                   custom_limits=custom_limits)
        if raw_path == None:
            return []
        path = [Conf(robot, get_se3_joints(robot), conf) for conf in raw_path]
        if visualize:
            set_renderer(True)
            for q in subsample_path(path, order=3):
                # wait_for_user('start?')
                q.assign()
                draw_pose(pose_from_se3(q.values), length=0.02)
                wait_for_duration(time_step)
            return raw_path
            q1.assign()
        t = Trajectory(path)
        cmd = Commands(State(), savers=[BodySaver(robot)], commands=[t])
        return (cmd,)
    return fn

def subsample_path(path, order=2, max_len=10, min_len=3):
    return path[::order]

def get_ik_fn(problem, teleport=False, verbose=True, custom_limits={}, **kwargs):
    robot = problem.robot
    joints = get_se3_joints(robot)
    obstacles = problem.fixed
    title = 'flying_gripper_utils.get_ik_fn |'
    def fn(a, o, p, g, w, fluents=[]):
        p.assign()
        w.assign()
        attachments = {}
        if isinstance(g, Grasp):
            attachment = g.get_attachment(problem.robot, a)
            attachments = {attachment.child: attachment}

        body_pose = robot.get_body_pose(o, verbose=verbose)
        # approach_pose = multiply(body_pose, invert(g.approach),
        #                          Pose(point=(0, 0, -0.05), euler=[0, math.pi / 2, 0]))
        # grasp_pose = multiply(body_pose, invert(g.value),
        #                       Pose(point=(0, 0, -0.05), euler=[0, math.pi / 2, 0]))
        approach_pose = multiply(body_pose, g.approach)
        grasp_pose = multiply(body_pose, g.value)
        if verbose:
            print(f'{title} | body_pose = {nice(body_pose)}')
            print(f'{title} | grasp_pose = {nice(grasp_pose)}')
            print(f'{title} | approach_pose = {nice(approach_pose)}')

        seconf1 = se3_ik(robot, approach_pose, verbose=verbose)
        seconf2 = se3_ik(robot, grasp_pose, verbose=verbose)
        q1 = Conf(robot, joints, seconf1)
        q2 = Conf(robot, joints, seconf2)
        q1.assign()
        if verbose:
            set_renderer(True)
        raw_path = plan_se3_motion(robot, q1.values, q2.values, obstacles=obstacles,
                                   custom_limits=custom_limits, attachments=attachments.values())
        if raw_path == None:
            return None
        path = [Conf(robot, get_se3_joints(robot), conf) for conf in raw_path]

        t = Trajectory(path)
        cmd = Commands(State(attachments=attachments), savers=[BodySaver(robot)], commands=[t])
        return (q1, cmd)
    return fn

def get_pull_door_handle_motion_gen(problem, custom_limits={}, collisions=True, teleport=False,
                                    num_intervals=30, max_ir_trial=30, visualize=False, verbose=False):
    if teleport:
        num_intervals = 1
    robot = problem.robot
    world = problem.world
    saver = BodySaver(robot)
    obstacles = problem.fixed if collisions else []

    def fn(a, o, pst1, pst2, g, q1, fluents=[]):
        if pst1.value == pst2.value:
            return None

        saver.restore()
        pst1.assign()
        q1.assign()

        arm_joints = get_arm_joints(robot, a)
        resolutions = 0.05 ** np.ones(len(arm_joints))

        BODY_TO_OBJECT = problem.world.BODY_TO_OBJECT
        joint_object = BODY_TO_OBJECT[o]
        old_pose = get_link_pose(joint_object.body, joint_object.handle_link)
        tool_from_root = get_tool_from_root(robot, a)
        if visualize:
            set_renderer(enable=True)
            gripper_before = robot.visualize_grasp(old_pose, g.value)
        gripper_before = multiply(old_pose, invert(g.value))  ## multiply(, tool_from_root)
        world_from_base = bconf_to_pose(bq1)
        gripper_from_base = multiply(invert(gripper_before), world_from_base)
        # print('gripper_before', nice(gripper_before))
        # print('invert(gripper_before)', nice(invert(gripper_before)))

        MOVE_BASE = True

        ## saving the mapping between robot bconf to object pst for execution
        mapping = {}
        rpose_rounded = tuple([round(n, 3) for n in bq1.values])
        mapping[rpose_rounded] = pst1.value

        bpath = []
        apath = []
        bq_after = Conf(bq1.body, bq1.joints, bq1.values)
        aq_after = Conf(aq1.body, aq1.joints, aq1.values)
        for i in range(num_intervals):
            step_str = f"pr2_streams.get_pull_door_handle_motion_gen | step {i}/{num_intervals}\t"
            value = (i + 1) / num_intervals * (pst2.value - pst1.value) + pst1.value
            pst_after = Position((pst1.body, pst1.joint), value)
            pst_after.assign()
            new_pose = get_link_pose(joint_object.body, joint_object.handle_link)
            if visualize:
                gripper_after = robot.visualize_grasp(new_pose, g.value, color=BROWN)
                set_camera_target_body(gripper_after, dx=0.2, dy=0, dz=1) ## look top down
                remove_body(gripper_after)
            gripper_after = multiply(new_pose, invert(g.value))  ## multiply(, tool_from_root)

            ## try to transform the base the same way as gripper to a cfree pose
            if MOVE_BASE:
                world_from_base = multiply(gripper_after, gripper_from_base)
                bq_after = pose_to_bconf(world_from_base, robot)

                bq_after.assign()
                if any(pairwise_collision(robot, b) for b in obstacles):
                    collided = []
                    for b in obstacles:
                        if pairwise_collision(robot, b):
                            collided.append(b)
                    collided = [world.BODY_TO_OBJECT[c].shorter_name for c in collided]
                    print(f'{step_str} base collide at {nice(world_from_base)} with {collided}')
                    MOVE_BASE = False
                    if len(bpath) > 1:
                        bpath[-1].assign()
                else:
                    bpath.append(bq_after)
                    apath.append(aq_after)
                    if verbose: print(f'{step_str} : {nice(bq_after.values)}\t{nice(aq_after.values)}')

            ## move the arm with IK
            if not MOVE_BASE and False:
                aq_after.assign()
                arm_conf = pr2_inverse_kinematics(robot, a, gripper_after)
                trial = 0
                while arm_conf is None: ## need to shift bq a bit
                    trial += 1
                    if trial > max_ir_trial:
                        break
                    bq_proposed = sample_new_bconf(bq_after)
                    bq_proposed.assign()
                    print(f'{step_str} Cant find arm_conf ({trial}) at {nice(bq_after.values)}, try {nice(bq_proposed.values)}')
                    arm_conf = pr2_inverse_kinematics(robot, a, gripper_after)
                    if arm_conf is not None:
                        collision_fn = get_collision_fn(robot, arm_joints, obstacles, self_collisions=SELF_COLLISIONS)
                        if collision_fn(arm_conf):
                            bq_after = bq_proposed
                            bpath.append(bq_after)
                            apath.append(aq_after)
                            print(f'{step_str} : {nice(bq_after.values)}\t{nice(aq_after.values)}')
                            break
                if trial > max_ir_trial:
                    break
                aq_after.assign()
                path = plan_joint_motion(robot, arm_joints, arm_conf, obstacles=obstacles, self_collisions=SELF_COLLISIONS,
                                         resolutions=resolutions, restarts=2, max_iterations=25, smooth=25)
                if path is None:
                    print(f'{step_str} Cant find arm path from {nice(aq_after.values)} to {nice(arm_conf)}')
                    break
                # elif len(path) > num_intervals/2:
                #     print(f'{step_str} adding arm_path of len ({len(path)})')
                blank = ''.join([' ']*90)
                path_str = f"\n{blank}".join([str(nice(ac)) for ac in path])
                print(f'{step_str} adding arm_path of len ({len(path)}) {path_str}')
                apath += create_trajectory(robot, arm_joints, path[1:]).path
                bpath += [bq_after] * len(path)
                aq_after = apath[-1]

            rpose_rounded = tuple([round(n, 3) for n in bq_after.values])
            mapping[rpose_rounded] = value

        if visualize:
            remove_body(gripper_before)

        if len(apath) < num_intervals: ## * 0.75:
            return None

        body, joint = o
        if body not in LINK_POSE_TO_JOINT_POSITION:
            LINK_POSE_TO_JOINT_POSITION[body] = {}
        # mapping = sorted(mapping.items(), key=lambda kv: kv[1])
        LINK_POSE_TO_JOINT_POSITION[body][joint] = mapping
        # print(f'pr2_streams.get_pull_door_handle_motion_gen | last bconf = {rpose_rounded}, pstn value = {value}')

        # apath.append(apath[-1])
        # bpath.append(bpath[-1]) ## replicate the last one because somehow it's missing
        bt = Trajectory(bpath)
        at = Trajectory(apath) ## create_trajectory(robot, get_arm_joints(robot, a), apath)
        base_cmd = Commands(State(), savers=[BodySaver(robot)], commands=[bt])
        arm_cmd =  Commands(State(), savers=[BodySaver(robot)], commands=[at])
        bq2 = bt.path[-1]
        aq2 = at.path[-1]
        if aq2.values == aq1.values:
            aq2 = aq1
        step_str = f"pr2_streams.get_pull_door_handle_motion_gen | step {len(bpath)}/{num_intervals}\t"
        if not verbose: print(f'{step_str} : {nice(bq2.values)}\t{nice(aq2.values)}')
        return (bq2, base_cmd, aq2, arm_cmd)

    return fn


from pybullet_tools.pr2_streams import get_grasp_gen
from pybullet_tools.bullet_utils import set_camera_target_body, nice
from pybullet_tools.utils import VideoSaver
from os.path import join
import math

def quick_demo(state, custom_limits):
    world = state.world
    robot = create_fe_gripper()
    problem = Problem(robot, state.fixed)
    lid = world.name_to_body('lid')
    # set_camera_target_body(lid, dx=0.6, dy=0.6, dz=0.3)
    set_camera_target_body(lid, dx=0.8, dy=0, dz=0.4)

    ## sample grasp
    g_sampler = get_grasp_gen(state)
    outputs = g_sampler(lid)
    g = outputs[0][0]
    body_pose = get_pose(lid)
    approach_pose = multiply(body_pose, invert(g.approach), Pose(point=(0, 0, -0.05), euler=[0, math.pi / 2, 0]))

    ## set approach pose as goal pose

    joints = get_se3_joints(robot)
    seconf1 = [0.9, 8, 0.7, 0, -math.pi/2, 0] ## [0.9, 8, 0.4, 0, 0, 0]
    seconf2 = [0.9, 8, 1.4, 0, 0, 0]
    seconf2 = se3_from_pose(approach_pose)
    q1 = Conf(robot, joints, seconf1)
    q2 = Conf(robot, joints, seconf2)
    q1.assign()

    ## plan and execute path, saving the first depth map and all se3 confs
    funk = get_free_motion_gen(problem, custom_limits, visualize=True, time_step=0.1)

    video_path = join('visualizations', 'video_tmp.mp4')
    with VideoSaver(video_path):
        raw_path = funk(q1, q2)
    state.world.visualize_image(((1.7, 8.1, 1), (0.5, 0.5, -0.5, -0.5)))

    ## output to json
    print('len(raw_path)', len(raw_path))

    with open('gripper_traj.txt', 'w') as f:
        f.write('\n'.join([str(nice(p)) for p in raw_path]))

    # wait_if_gui('end?')
    sys.exit()
