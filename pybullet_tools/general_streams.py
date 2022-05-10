from __future__ import print_function

import copy
import pybullet as p
import random
import time
import os
from itertools import islice, count
import math
import json

import numpy as np

from pybullet_tools.pr2_problems import get_fixed_bodies, create_pr2
from pybullet_tools.pr2_utils import TOP_HOLDING_LEFT_ARM, SIDE_HOLDING_LEFT_ARM, GET_GRASPS, get_gripper_joints, \
    get_carry_conf, get_top_grasps, get_side_grasps, open_arm, arm_conf, get_gripper_link, get_arm_joints, \
    learned_pose_generator, PR2_TOOL_FRAMES, get_x_presses, PR2_GROUPS, joints_from_names, \
    is_drake_pr2, get_group_joints, get_group_conf, compute_grasp_width, PR2_GRIPPER_ROOTS, \
    TOOL_POSE, MAX_GRASP_WIDTH, GRASP_LENGTH, SIDE_HEIGHT_OFFSET, approximate_as_prism, set_group_conf
from pybullet_tools.pr2_primitives import control_commands, apply_commands, Grasp, \
    APPROACH_DISTANCE, TOP_HOLDING_LEFT_ARM, get_tool_from_root, Conf, Commands, State, create_trajectory, \
    Trajectory, get_cfree_approach_pose_test, get_cfree_pose_pose_test, get_cfree_traj_pose_test, \
    move_cost_fn, get_ik_ir_gen, get_motion_gen, Attach, Detach, Clean, \
    Cook, control_commands, get_gripper_joints, GripperCommand, apply_commands, State
from pybullet_tools.ikfast.pr2.ik import is_ik_compiled, pr2_inverse_kinematics
from pybullet_tools.utils import invert, multiply, get_name, set_pose, get_link_pose, is_placement, \
    pairwise_collision, set_joint_positions, get_joint_positions, sample_placement, get_pose, waypoints_from_path, \
    unit_quat, plan_base_motion, plan_joint_motion, base_values_from_pose, pose_from_base_values, \
    uniform_pose_generator, sub_inverse_kinematics, add_fixed_constraint, remove_debug, remove_fixed_constraint, \
    disable_real_time, enable_gravity, joint_controller_hold, get_distance, Point, Euler, set_joint_position, \
    get_min_limit, user_input, step_simulation, get_body_name, get_bodies, BASE_LINK, get_joint_position, \
    add_segments, get_max_limit, link_from_name, BodySaver, get_aabb, Attachment, interpolate_poses, \
    plan_direct_joint_motion, has_gui, create_attachment, wait_for_duration, get_extend_fn, set_renderer, \
    get_custom_limits, all_between, get_unit_vector, wait_if_gui, create_box, set_point, quat_from_euler, \
    set_base_values, euler_from_quat, INF, elapsed_time, get_moving_links, flatten_links, get_relative_pose, \
    get_joint_limits, unit_pose, point_from_pose, clone_body, set_all_color, GREEN, BROWN, get_link_subtree, \
    RED, remove_body, aabb2d_from_aabb, aabb_overlap, aabb_contains_point, get_aabb_center, get_link_name, \
    get_links, check_initial_end, get_collision_fn, BLUE, WHITE, TAN, GREY, YELLOW, aabb_contains_aabb, \
    get_joints, is_movable, pairwise_link_collision, get_closest_points, Pose

from pybullet_tools.bullet_utils import sample_obj_in_body_link_space, nice, set_camera_target_body, is_contained, \
    visualize_point, collided, GRIPPER_DIRECTIONS, get_gripper_direction
from pybullet_tools.logging import dump_json


class Position(object):
    num = count()
    def __init__(self, body_joint, value=None, index=None):
        self.body, self.joint = body_joint
        if value is None:
            value = get_joint_position(self.body, self.joint)
        elif value == 'max':
            value = self.get_limits()[1]
        elif value == 'min':
            value = self.get_limits()[0]
        self.value = float(value)
        if index == None: index = next(self.num)
        self.index = index
    @property
    def bodies(self):
        return flatten_links(self.body)
    @property
    def extent(self):
        if self.value == self.get_limits()[1]:
            return 'max'
        elif self.value == self.get_limits()[0]:
            return 'min'
        return 'middle'
    def assign(self):
        set_joint_position(self.body, self.joint, self.value)
    def iterate(self):
        yield self
    def get_limits(self):
        return get_joint_limits(self.body, self.joint)
    def __repr__(self):
        index = self.index
        #index = id(self) % 1000
        return 'pstn{}={}'.format(index, nice(self.value))

class LinkPose(object):
    num = count()
    def __init__(self, body, obj, value=None, support=None, init=False):
        self.obj = obj
        self.link = self.obj.handle_link
        self.body, self.joint = body
        if value is None:
            value = get_link_pose(self.body, self.link)
        self.value = tuple(value)
        self.body_pose = get_pose(self.body)
        self.support = support
        self.init = init
        self.index = next(self.num)
    @property
    def bodies(self):
        return flatten_links(self.body)
    def assign(self):
        pass
    def iterate(self):
        yield self
    # def to_base_conf(self):
    #     values = base_values_from_pose(self.value)
    #     return Conf(self.body, range(len(values)), values)
    def __repr__(self):
        index = self.index
        #index = id(self) % 1000
        return 'lp{}={}'.format(index, nice(self.value))
        # return 'p{}'.format(index)

class HandleGrasp(object):
    def __init__(self, grasp_type, body, value, approach, carry):
        self.grasp_type = grasp_type
        self.body = body
        self.value = tuple(value) # gripper_from_object
        self.approach = tuple(approach)
        self.carry = tuple(carry)
    def get_attachment(self, robot, arm):
        tool_link = link_from_name(robot, PR2_TOOL_FRAMES[arm])
        return Attachment(robot, tool_link, self.value, self.body)
    def __repr__(self):
        return 'hg{}={}'.format(id(self) % 1000, nice(self.value))

class WConf(object):
    def __init__(self, poses, positions):
        self.poses = poses
        self.positions = positions
    def assign(self):
        for p in self.poses.values():
            p.assign()
        for p in self.positions.values():
            p.assign()
    def printout(self, obstacles=None):
        if obstacles == None:
            obstacles = list(self.poses.keys())
            positions = list(self.positions.keys())
        else:
            positions = [o for o in self.positions.keys() if o[0] in obstacles]

        string = f"  {str(self)}"
        poses = {o: nice(self.poses[o].value[0]) for o in obstacles if o in self.poses}
        if len(poses) > 0:
            string += f'\t|\tposes: {str(poses)}'
        positions = {o: nice(self.positions[(o[0], o[1])].value) for o in positions}
        if len(positions) > 0:
            string += f'\t|\tpositions: {str(positions)}'
        # print(string)
        return string

    def __repr__(self):
        return 'wconf{}({})'.format(id(self) % 1000, len(self.poses))

##################################################
def get_stable_gen(problem, collisions=True, num_trials=20, **kwargs):
    from pybullet_tools.pr2_primitives import Pose
    obstacles = problem.fixed if collisions else []
    world = problem.world
    def gen(body, surface):
        if surface is None:
            surfaces = problem.surfaces
        else:
            surfaces = [surface]
        count = num_trials
        while count > 0: ## True
            count -= 1
            surface = random.choice(surfaces) # TODO: weight by area
            if isinstance(surface, tuple): ## (body, link)
                body_pose = sample_placement(body, surface[0], bottom_link=surface[-1], **kwargs)
            else:
                body_pose = sample_placement(body, surface, **kwargs)
            if body_pose is None:
                break

            ## hack to reduce planning time
            body_pose = learned_pose_sampler(world, body, surface, body_pose)

            p = Pose(body, body_pose, surface)
            p.assign()
            if not any(pairwise_collision(body, obst) for obst in obstacles if obst not in {body, surface}):
                yield (p,)
    return gen

def learned_pose_sampler(world, body, surface, body_pose):
    ## hack to reduce planning time
    if 'eggblock' in world.get_name(body) and 'braiser_bottom' in world.get_name(surface):
        (x, y, z), quat = body_pose
        x = 0.55
        body_pose = (x, y, z), quat
    return body_pose

def get_contain_gen(problem, collisions=True, max_attempts=20, verbose=False, **kwargs):
    from pybullet_tools.pr2_primitives import Pose
    obstacles = problem.fixed if collisions else []

    def gen(body, space):
        if space is None:
            spaces = problem.spaces
        else:
            spaces = [space]
        attempts = 0
        while attempts < max_attempts:
            attempts += 1
            space = random.choice(spaces)  # TODO: weight by area
            if isinstance(space, tuple):
                x, y, z, yaw = sample_obj_in_body_link_space(body, space[0], space[-1],
                                        PLACEMENT_ONLY=True, verbose=verbose, **kwargs)
                body_pose = ((x, y, z), quat_from_euler(Euler(yaw=yaw)))
            else:
                body_pose = None
            if body_pose is None:
                break
            p = Pose(body, body_pose, space)
            p.assign()
            if not any(pairwise_collision(body, obst) for obst in obstacles if obst not in {body, space}):
                yield (p,)
        if verbose:
            print(f'  get_contain_gen | reached max_attempts = {max_attempts}')
        yield None
    return gen

def get_pose_in_space_test():
    def test(o, p, r):
        p.assign()
        answer = is_contained(o, r)
        print(f'pr2_streams.get_pose_in_space_test({o}, {p}, {r}) = {answer}')
        return answer
    return test

########################################################################

def get_joint_position_open_gen(problem):
    def fn(o, psn1, fluents=[]):  ## ps1,
        if psn1.extent == 'max':
            psn2 = Position(o, 'min')
        elif psn1.extent == 'min':
            psn2 = Position(o, 'max')
        return (psn2,)
    return fn

def sample_joint_position_open_list_gen(problem, num_samples = 3):
    def fn(o, psn1, fluents=[]):
        psn2 = None
        if psn1.extent == 'max':
            psn2 = Position(o, 'min')
            higher = psn1.value
            lower = psn2.value
        elif psn1.extent == 'min':
            psn2 = Position(o, 'max')
            higher = psn2.value
            lower = psn1.value
        else:
            # return [(psn1, )]
            higher = Position(o, 'max').value
            lower = Position(o, 'min').value
            if lower > higher:
                sometime = lower
                lower = higher
                higher = sometime

        positions = []
        if psn2 == None or abs(psn1.value - psn2.value) > math.pi/2:
            # positions.append((Position(o, lower+math.pi/2), ))
            lower += math.pi/2
            higher = lower + math.pi/8
            ptns = [np.random.uniform(lower, higher) for k in range(num_samples)]
            ptns.append(1.77)
            positions.extend([(Position(o, p), ) for p in ptns])
        else:
            positions.append((psn2,))

        return positions
    return fn

## discarded
def get_position_gen(problem, collisions=True, extent=None):
    obstacles = problem.fixed if collisions else []
    def fn(o, fluents=[]):  ## ps1,
        ps2 = Position(o, extent)
        return (ps2,)
    return fn

## discarded
def get_joint_position_test(extent='max'):
    def test(o, pst):
        pst_max = Position(o, extent)
        if pst_max.value == pst.value:
            return True
        return False
    return test

################# HANDLE GRASPS #############

def get_handle_link(body_joint):
    from world_builder.entities import ArticulatedObjectPart
    body, joint = body_joint
    j = ArticulatedObjectPart(body, joint)
    return j.handle_link

def get_handle_pose(body_joint):
    from world_builder.entities import ArticulatedObjectPart
    body, joint = body_joint
    j = ArticulatedObjectPart(body, joint)
    return j.get_handle_pose()

def get_handle_width(body_joint):
    from world_builder.entities import ArticulatedObjectPart
    body, joint = body_joint
    j = ArticulatedObjectPart(body, joint)
    return j.handle_width


################# GRASPS #############

def get_top_grasps(body, under=False, tool_pose=TOOL_POSE, body_pose=unit_pose(),
                   max_width=MAX_GRASP_WIDTH, grasp_length=GRASP_LENGTH):
    ## debug grasp orientation
    for link in get_links(body):
        new_vertices = apply_affine(origin, vertices_from_rigid(body, link))

    # TODO: rename the box grasps
    # center, (w, l, h) = approximate_as_prism(body, body_pose=body_pose)
    reflect_z = Pose(euler=[0, math.pi, 0])
    translate_z = Pose(point=[0, 0, h / 2 - grasp_length])
    translate_center = Pose(point=point_from_pose(body_pose)-center)
    grasps = []
    if w <= max_width:
        for i in range(1 + under):
            rotate_z = Pose(euler=[0, 0, math.pi / 2 + i * math.pi])
            grasps += [multiply(tool_pose, translate_z, rotate_z,
                                reflect_z, translate_center, body_pose)]
    if l <= max_width:
        for i in range(1 + under):
            rotate_z = Pose(euler=[0, 0, i * math.pi])
            grasps += [multiply(tool_pose, translate_z, rotate_z,
                                reflect_z, translate_center, body_pose)]
    return grasps

def get_side_grasps(body, under=False, tool_pose=TOOL_POSE, body_pose=unit_pose(),
                    max_width=MAX_GRASP_WIDTH, grasp_length=GRASP_LENGTH, top_offset=SIDE_HEIGHT_OFFSET):
    # TODO: compute bounding box width wrt tool frame
    center, (w, l, h) = approximate_as_prism(body, body_pose=body_pose)
    translate_center = Pose(point=point_from_pose(body_pose)-center)
    grasps = []
    #x_offset = 0
    x_offset = h/2 - top_offset
    for j in range(1 + under):
        swap_xz = Pose(euler=[0, -math.pi / 2 + j * math.pi, 0])
        if w <= max_width:
            translate_z = Pose(point=[x_offset, 0, l / 2 - grasp_length])
            for i in range(2):
                rotate_z = Pose(euler=[math.pi / 2 + i * math.pi, 0, 0])
                grasps += [multiply(tool_pose, translate_z, rotate_z, swap_xz,
                                    translate_center, body_pose)]  # , np.array([w])
        if l <= max_width:
            translate_z = Pose(point=[x_offset, 0, w / 2 - grasp_length])
            for i in range(2):
                rotate_z = Pose(euler=[i * math.pi, 0, 0])
                grasps += [multiply(tool_pose, translate_z, rotate_z, swap_xz,
                                    translate_center, body_pose)]  # , np.array([l])
    return grasps