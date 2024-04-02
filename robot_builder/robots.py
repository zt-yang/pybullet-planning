import math
import time
import copy
import random
from os.path import basename
from world_builder.entities import Robot

from pybullet_tools.utils import get_joint_positions, clone_body, set_all_color, TRANSPARENT, \
    link_from_name, multiply, invert, LockRenderer, unit_point, draw_aabb, get_aabb, \
    set_joint_positions, set_pose, GREEN, get_pose, remove_body, PoseSaver, get_relative_pose, \
    ConfSaver, get_unit_vector, unit_quat, get_link_pose, unit_pose, draw_pose, remove_handles, \
    interpolate_poses, Pose, Euler, quat_from_euler, get_bodies, get_all_links, PI, \
    is_darwin, wait_for_user, YELLOW, euler_from_quat, wait_unlocked, set_renderer, \
    sub_inverse_kinematics

from pybullet_tools.bullet_utils import equal, nice, set_camera_target_body, Attachment, \
    collided, query_yes_no, has_tracik, is_mesh_entity, get_rotation_matrix
from pybullet_tools.pr2_primitives import APPROACH_DISTANCE, Conf, Grasp, get_base_custom_limits
from pybullet_tools.pr2_utils import PR2_TOOL_FRAMES, PR2_GROUPS, TOP_HOLDING_LEFT_ARM, PR2_GRIPPER_ROOTS
from pybullet_tools.general_streams import get_handle_link, get_grasp_list_gen, get_contain_list_gen, \
    get_cfree_approach_pose_test, get_stable_list_gen, play_trajectory
from pybullet_tools.stream_agent import remove_stream_by_name

from world_builder.world_utils import load_asset

from robot_builder.robot_utils import get_robot_group_joints, close_until_collision, \
    create_robot_gripper, BASE_GROUP, BASE_TORSO_GROUP, get_cloned_gripper_joints, \
    get_joints_by_names, test_tool_from_root_transformations


class RobotAPI(Robot):

    arms = []
    tool_from_hand = unit_pose()
    joint_groups = dict()

    def __init__(self, body, **kwargs):
        super(RobotAPI, self).__init__(body, **kwargs)
        self.grippers = {}
        self.possible_obstacles = {}  ## body: obstacles
        self.collision_animations = []
        self.name = self.__class__.__name__.lower()
        self.ik_solver = None
        self.debug_handles = []

    def get_lisdf_string(self):
        raise NotImplementedError('should implement this for RobotAPI!')

    def get_init(self, init_facts=[], conf_saver=None):
        raise NotImplementedError('should implement this for RobotAPI!')

    def get_stream_map(self, problem, collisions, custom_limits, teleport, **kwargs):
        raise NotImplementedError('should implement this for RobotAPI!')

    def get_gripper_root(self, arm):
        raise NotImplementedError('should implement this for MobileRobot!')

    def get_tool_link(self, arm):
        raise NotImplementedError('should implement this for RobotAPI!')

    def get_gripper_joints(self, arm):
        raise NotImplementedError('should implement this for RobotAPI!')

    def visualize_grasp(self, body_pose, grasp, arm='left', color=GREEN, **kwargs):
        raise NotImplementedError('should implement this for RobotAPI!')

    def get_carry_conf(self, arm, grasp_type, g):
        raise NotImplementedError('should implement this for RobotAPI!')

    def create_gripper(self, arm='hand', visual=True, color=None):
        raise NotImplementedError('should implement this for RobotAPI!')

    def _open_cloned_gripper(self, gripper_cloned, arm, width=1):
        raise NotImplementedError('should implement this for RobotAPI!')

    def _close_cloned_gripper(self, gripper_cloned, arm):
        raise NotImplementedError('should implement this for RobotAPI!')

    def open_cloned_gripper(self, gripper_cloned, arm=None, width=1):
        if arm is None:
            arm = self.get_arm_from_gripper(gripper_cloned)
        self._open_cloned_gripper(gripper_cloned, arm, width=1)

    def close_cloned_gripper(self, gripper_cloned, arm=None):
        if arm is None:
            arm = self.get_arm_from_gripper(gripper_cloned)
        self._close_cloned_gripper(gripper_cloned, arm)

    def get_gripper_end_conf(self, arm, width):
        if arm is None:
            arm = self.arms[0]
        gripper_joints = self.get_gripper_joints(arm)
        return [width] * len(gripper_joints)

    ## ------------------------------------------------------------------

    def get_arm_from_gripper(self, gripper):
        arms = [a for a in self.grippers if self.grippers[a] == gripper]
        if len(arms) > 0:
            return arms[0]
        return None

    def get_tool_from_root(self, arm):
        root_link = link_from_name(self.body, self.get_gripper_root(arm))
        tool_link = link_from_name(self.body, self.get_tool_link(arm))
        tool_from_root = get_relative_pose(self.body, root_link, tool_link)
        # print('robot.tool_from_root\t', nice(tool_from_root))
        return tool_from_root

    def get_approach_vector(self, arm, grasp_type, scale=1):
        return tuple(scale * APPROACH_DISTANCE * get_unit_vector([0, 0, -1]))

    def get_approach_pose(self, approach_vector, g):
        return multiply(g, (approach_vector, unit_quat()))

    def get_all_joints(self):
        return sum([v for k, v in self.joint_groups.items() if k != BASE_TORSO_GROUP], [])

    def get_custom_limits(self):
        return self.custom_limits

    def iterate_approach_path(self, arm, gripper, pose_value, grasp, body=None):
        tool_from_root = self.get_tool_from_root(arm)
        grasp_pose = multiply(pose_value, invert(grasp.value))
        approach_pose = multiply(pose_value, invert(grasp.approach))
        for tool_pose in interpolate_poses(grasp_pose, approach_pose):
            set_pose(gripper, multiply(tool_pose, tool_from_root))
            yield

    def get_gripper(self, arm=None, **kwargs):
        if arm is None:
            arm = self.arms[0]
        if arm not in self.grippers or self.grippers[arm] not in get_bodies():
            self.grippers[arm] = self.create_gripper(arm=arm, **kwargs)
        return self.grippers[arm]

    def load_gripper(self, arm, color=GREEN, new_gripper=False):
        if new_gripper:
            gripper = self.create_gripper(arm)
        else:
            gripper = self.get_gripper(arm, visual=True)
        if color is not None:
            set_all_color(gripper, color)
        return gripper

    def make_grasps(self, g_type, arm, body, grasps_O, collisions=True):
        from pybullet_tools.general_streams import is_top_grasp
        app = self.get_approach_vector(arm, g_type)
        grasps_R = []
        for g in grasps_O:
            if False and is_top_grasp(self, arm, body, g, get_pose(body)):
                approach = g
            else:
                approach = self.get_approach_pose(app, g)
            grasps_R.append(Grasp(g_type, body, g, approach,
                                  self.get_carry_conf(arm, g_type, g)))

        ## filter for grasp width
        filtered_grasps = []
        for grasp in grasps_R:
            grasp_width = self.compute_grasp_width(arm, grasp, body=body) if collisions else 0.0
            if grasp_width is not None:
                grasp.grasp_width = grasp_width
                filtered_grasps.append(grasp)
        return filtered_grasps

    def make_attachment(self, grasp, arm, visualize=False):
        tool_link = self.get_attachment_link(arm)
        o = grasp.body
        if isinstance(o, tuple) and len(o) == 2:
            body, joint = o
            link = get_handle_link(o)
            return Attachment(self, tool_link, grasp.value, body, child_joint=joint, child_link=link)

        arm = self.arms[0]
        child_pose = get_pose(o)
        tool_from_root = self.get_tool_from_root(arm)

        def get_attachment(tool_from_root):
            grasp_pose = self.get_grasp_pose(child_pose, grasp.value, body=o)
            gripper_pose = multiply(grasp_pose, invert(tool_from_root))
            grasp_pose = multiply(invert(gripper_pose), child_pose)
            attachment = Attachment(self, tool_link, grasp_pose, grasp.body)
            return attachment

        attachment = get_attachment(tool_from_root)
        if visualize:
            with PoseSaver(attachment.child):
                set_renderer(True)
                set_camera_target_body(o)
                attachment.assign()
                print('collided?\t', collided(self.body, [o], articulated=True, use_aabb=True))
                test_tool_from_root_transformations(tool_from_root, get_attachment,
                                                    test_rotation=True, test_translation=False)

        return attachment

    ###############################################################################

    def get_grasp_pose(self, body_pose, grasp, arm='left', body=None, verbose=False):
        ## those primitive shapes
        if body is not None and isinstance(body, int) and len(get_all_links(body)) == 1:
            tool_from_root = multiply(((0, 0.025, 0.025), unit_quat()), self.tool_from_hand)  ## self.get_tool_from_root(arm)
        ## those urdf files made from one .obj file
        else:
            body_pose = self.get_body_pose(body_pose, body=body, verbose=verbose)
            tool_from_root = ((0, 0, -0.05), quat_from_euler((math.pi / 2, -math.pi / 2, -math.pi)))
        return multiply(body_pose, grasp, tool_from_root)

    def get_body_pose(self, body_pose, body=None, verbose=False):
        title = f'    robot.get_body_pose({nice(body_pose)}, body={body})'

        ## if body_pose is handle link pose and body is (body, joint)
        if body is not None and isinstance(body, tuple) and not isinstance(body[0], tuple):
            if verbose: print(f'{title} | return as is')
            return body_pose

        ## if body or body_joint is given in the place of body_pose
        b = body_pose
        if not (isinstance(b, tuple) and isinstance(b[0], tuple) and len(b[0]) == 3 and len(b[1]) == 4):
            if isinstance(b, tuple):
                handle_link = get_handle_link(b)
                new_body_pose = get_link_pose(b[0], handle_link)
                if verbose: print(f'{title} | actually given (body, joint), multiply(get_link_pose(body, '
                                  f'handle_link), invert(T)) = {nice(new_body_pose)}')
                return new_body_pose
            else:
                body_pose = get_pose(b)
                if verbose: print(f'{title} | actually given body, body_pose = get_pose(b) = {nice(body_pose)}')

        r = get_rotation_matrix(body) if body is not None else self.tool_from_hand
        new_body_pose = multiply(body_pose, r)
        return new_body_pose

    def set_spawn_range(self, limits):
        self.spawn_range = limits

    def get_attachment_link(self, arm):
        return link_from_name(self.body, self.get_tool_link(arm))

    ################################################################################

    def get_group_joints(self, group):
        assert group in self.joint_groups
        return get_robot_group_joints(self.body, group, self.joint_groups)

    def get_positions(self, joint_group=None, roundto=None):
        if joint_group is None:
            joint_group = self.base_group
        joints = self.get_group_joints(joint_group)
        positions = self.get_joint_positions(joints)
        if roundto is None:
            return positions
        return tuple([round(n, roundto) for n in positions])

    def set_group_positions(self, joint_group: str, positions: list):
        joints = self.get_group_joints(joint_group)
        assert len(joints) == len(positions)
        self.set_joint_positions(joints, positions)

    def compute_grasp_width(self, arm, grasp, body=None, **kwargs):
        with PoseSaver(body):
            with ConfSaver(self.body):
                assignment = self.make_attachment(grasp, arm)
                assignment.assign()
                gripper_joints = self.get_gripper_joints(arm)
                result = self.close_until_collision(gripper_joints, bodies=[body], **kwargs)
        return result

    def close_until_collision(self, gripper_joints, bodies, **kwargs):
        return close_until_collision(self.body, gripper_joints, bodies=bodies, **kwargs)

    def update_stream_pddl(self, pddlstream_problem):
        pass

    def remove_grippers(self):
        for body in self.grippers.values():
            self.remove_gripper(body)

    def remove_gripper(self, gripper_handle):
        remove_body(gripper_handle)


class MobileRobot(RobotAPI):

    arms = None
    grasp_types = ['top', 'side']

    def __init__(self, body, use_torso=True, move_base=True, **kwargs):
        self.base_group = BASE_TORSO_GROUP if use_torso else BASE_GROUP
        joints = self.joint_groups[self.base_group]
        super(MobileRobot, self).__init__(body, joints=joints, **kwargs)
        self.use_torso = use_torso
        self.move_base = move_base

    def get_arm_joints(self, arm):
        raise NotImplementedError('should implement this for MobileRobot!')

    def open_arm(self, arm):
        raise NotImplementedError('should implement this for MobileRobot!')

    ## -----------------------------------------------------------------------------

    def get_base_joints(self):
        return self.get_group_joints(self.base_group)

    def get_base_conf(self):
        base_joints = self.get_base_joints()
        q = get_joint_positions(self.body, base_joints)
        return Conf(self.body, base_joints, q)

    def set_pose(self, conf):
        self.set_group_positions(self.base_group, conf)

    def get_all_arms(self):
        return self.arms

    def get_arm_conf(self, arm):
        return Conf(self.body, self.get_arm_joints(arm))

    def get_init(self, init_facts=[], conf_saver=None):
        robot = self.body

        def get_conf(joints):
            if conf_saver is None:
                return get_joint_positions(robot, joints)
            return [conf_saver.conf[conf_saver.joints.index(n)] for n in joints]

        def get_base_conf():
            base_joints = self.get_group_joints(BASE_GROUP)
            initial_bq = Conf(robot, base_joints, get_conf(base_joints))
            for fact in init_facts:
                if fact[0] == 'bconf' and equal(fact[1].values, initial_bq.values):
                    return fact[1]
            return initial_bq

        def get_base_torso_conf():
            base_joints = self.get_group_joints(BASE_TORSO_GROUP)
            initial_bq = Conf(robot, base_joints, get_conf(base_joints))
            for fact in init_facts:
                if fact[0] == 'btconf' and equal(fact[1].values, initial_bq.values):
                    return fact[1]
            return initial_bq

        def get_arm_conf(arm):
            arm_joints = self.get_arm_joints(arm)
            conf = Conf(robot, arm_joints, get_conf(arm_joints))
            for fact in init_facts:
                if fact[0] == 'aconf' and fact[1] == arm and equal(fact[2].values, conf.values):
                    return fact[2]
            return conf

        initial_bq = get_base_torso_conf() if self.use_torso else get_base_conf()
        init = [('BConf', initial_bq), ('AtBConf', initial_bq)]

        for arm in self.get_all_arms():
            conf = get_arm_conf(arm)
            init += [('Arm', arm), ('AConf', arm, conf), ('AtAConf', arm, conf),
                     ('DefaultAConf', arm, conf), ('HandEmpty', arm)]
            if arm in self.arms:
                init += [('Controllable', arm)]

        if self.move_base:
            init += [('CanMoveBase',)]
        return init

    def get_stream_map(self, problem, collisions, custom_limits, teleport, domain_pddl=None, **kwargs):
        from pybullet_tools.stream_agent import get_stream_map
        stream_map = get_stream_map(problem, collisions, custom_limits, teleport, **kwargs)
        if self.move_base:
            stream_map.pop('test-inverse-reachability')
        return stream_map

    def update_stream_pddl(self, pddlstream_problem):
        from pddlstream.language.constants import PDDLProblem
        if self.move_base:
            domain_pddl, constant_map, stream_pddl, stream_map, init, goal = pddlstream_problem
            stream_pddl = pddlstream_problem[2]
            stream_pddl = remove_stream_by_name(stream_pddl, 'test-inverse-reachability')
            pddlstream_problem = PDDLProblem(domain_pddl, constant_map, stream_pddl, stream_map, init, goal)
        return pddlstream_problem

    def get_stream_info(self, **kwargs):
        from pybullet_tools.stream_agent import get_stream_info
        return get_stream_info() ## partial=partial, defer=defer

    ###############################################################################

    def create_gripper(self, arm=None, **kwargs):
        self.grippers[arm] = create_robot_gripper(self.body, self.get_gripper_root(arm), **kwargs)
        return self.grippers[arm]

    def set_gripper_pose(self, body_pose, grasp, body=None, gripper=None, arm='left', **kwargs):
        if gripper is None:
            gripper = self.get_gripper(arm, **kwargs)
        grasp_pose = self.get_grasp_pose(body_pose, grasp, arm, body=body, **kwargs)
        set_pose(gripper, grasp_pose)
        return gripper

    def visualize_grasp(self, body_pose, grasp, arm='left', color=GREEN, cache=False,
                        new_gripper=False, width=None, **kwargs):
        gripper = self.load_gripper(arm, color=color, new_gripper=new_gripper)
        self.set_gripper_pose(body_pose, grasp, gripper=gripper, arm=arm, **kwargs)
        if width is not None:
            self.open_cloned_gripper(gripper, arm, width)
        else:
            self.open_cloned_gripper(gripper, arm)
        return gripper

    def mod_grasp_along_handle(self, grasp, dl):
        return multiply(grasp, Pose(point=(0, dl, 0)))

    ## -------------------------------------------------------------

    def run_ik_once(self, arm, gripper_pose, tool_link, arm_joint):
        """ by default, assume IKFast is not compiled """
        kwargs = dict(custom_limits=self.custom_limits)
        if has_tracik():
            from pybullet_tools.tracik import IKSolver
            if self.ik_solver is None:

                self.ik_solver = IKSolver(self.body, tool_link=tool_link, first_joint=arm_joint, **kwargs)
            current_conf = self.get_arm_conf(arm).values
            return self.ik_solver.solve(gripper_pose, seed_conf=current_conf)

        else:
            return sub_inverse_kinematics(self.body, arm_joint, tool_link, gripper_pose, **kwargs)

    def inverse_kinematics(self, arm, gripper_pose, obstacles, attempts=10, verbose=True, visualize=False):
        tool_link = self.get_tool_link(arm)
        arm_joints = self.get_arm_joints(arm)
        title = 'robots.inverse_kinematics | '
        kwargs = dict(obstacles=obstacles, verbose=verbose, visualize=visualize, world=self.world)

        result = None
        with ConfSaver(self.body):
            for i in range(attempts):
                arm_conf = self.run_ik_once(arm, gripper_pose, tool_link, arm_joints[0])
                if arm_conf is None:
                    continue
                self.set_joint_positions(arm_joints, arm_conf)
                if not collided(self.body, tag='robot.TracIK', **kwargs):
                    result = arm_conf
                    if verbose:
                        print(title, f'found cfree ik for arm in attempt {i}/{attempts}')
                    break

        if result is not None:
            return arm_conf
            # base_joints = self.get_base_joints()
            # base_conf = self.get_base_conf()
            # joint_state = dict(zip(base_joints + arm_joints, list(base_conf.values) + arm_conf.tolist()))
            # return Conf(self.body, arm_joints, arm_conf, joint_state=joint_state)
        if verbose:
            print(title, f'didnt found cfree ik for arm after {attempts} attempts')
        return None




###############################################################################


from robot_builder.spot_utils import SPOT_TOOL_LINK, SPOT_CARRY_ARM_CONF, SPOT_JOINT_GROUPS


class SpotRobot(MobileRobot):

    arms = ['hand']
    joint_groups = SPOT_JOINT_GROUPS
    joint_group_names = ['hand', BASE_TORSO_GROUP]
    tool_link = SPOT_TOOL_LINK
    cloned_finger_link = 1  ## for detecting if a grasp is pointing upwards

    def __init__(self, body, base_link=BASE_GROUP, **kwargs):
        joints = self.joint_groups[BASE_TORSO_GROUP]
        super(SpotRobot, self).__init__(body, base_link=base_link, joints=joints, **kwargs)

    def get_arm_joints(self, arm):
        return self.get_group_joints('arm')

    def get_gripper_joints(self, arm):
        return self.get_group_joints('gripper')

    def _close_cloned_gripper(self, gripper_cloned, arm):
        joints = get_cloned_gripper_joints(gripper_cloned)
        set_joint_positions(gripper_cloned, joints, [0, 0])

    def _open_cloned_gripper(self, gripper_cloned, arm, width=-math.pi/2):
        joints = get_cloned_gripper_joints(gripper_cloned)
        set_joint_positions(gripper_cloned, joints, [0, width])

    # def get_stream_map(self, problem, collisions, custom_limits, teleport,
    #                    domain_pddl=None, **kwargs):
    #     from pybullet_tools.pr2_agent import get_stream_map
    #     stream_map = get_stream_map(problem, collisions, custom_limits, teleport, **kwargs)
    #     # stream_map = {k: v for k, v in stream_map.items() if k in {
    #     #     'sample-pose', 'sample-grasp', 'sample-grasp', 'sample-grasp'
    #     # }}
    #     return stream_map

    def get_carry_conf(self, arm, g_type, g):
        return SPOT_CARRY_ARM_CONF

    def get_tool_from_root(self, a):
        return Pose(euler=Euler(math.pi / 2, 0, -math.pi / 2))


from pybullet_tools.pr2_utils import open_arm


class PR2Robot(MobileRobot):

    arms = ['left']
    joint_groups = PR2_GROUPS
    joint_group_names = ['left', 'right', BASE_GROUP, BASE_TORSO_GROUP]
    tool_from_hand = Pose(euler=Euler(math.pi / 2, 0, -math.pi / 2))
    cloned_finger_link = 7  ## for detecting if a grasp is pointing upwards

    torso_lift_joint = 'torso_lift_joint'
    head_pan_joint = 'head_pan_joint'
    head_tilt_joint = 'head_tilt_joint'

    def __init__(self, body, dual_arm=False, **kwargs):
        super(PR2Robot, self).__init__(body, **kwargs)
        self.dual_arm = dual_arm
        self.grasp_aconfs = {}
        ## get away with the problem of Fluent stream outputs cannot be in action effects: ataconf

    def get_lisdf_string(self):
        return """
    <include name="{name}">
      <uri>../../pybullet_planning/models/drake/pr2_description/urdf/pr2_simplified.urdf</uri>
      {pose_xml}
    </include>
"""

    def open_arm(self, arm):
        open_arm(self.body, arm)

    def get_arm_joints(self, arm):
        from pybullet_tools.pr2_utils import get_arm_joints
        return get_arm_joints(self.body, arm)

    def get_group_joints(self, group):
        from pybullet_tools.pr2_utils import get_group_joints
        return get_group_joints(self.body, group)

    def get_all_arms(self):
        from pybullet_tools.pr2_utils import ARM_NAMES
        return ARM_NAMES

    def add_collision_grasp(self, a, o, g):
        from world_builder.actions import AttachObjectAction
        act = AttachObjectAction(a, g, o)
        to_add = str(act)
        added = [str(c) for c in self.collision_animations]
        if to_add not in added:
            self.collision_animations.append(act)

    def add_collision_conf(self, conf):  ## bconf, aconf
        from world_builder.actions import MoveArmAction
        import pickle
        # joints = bconf.joints + aconf.joints
        # values = bconf.values + aconf.values
        # conf = Conf(bconf.body, joints, values)
        self.collision_animations.append(MoveArmAction(conf))
        with open('collisions.pkl', 'wb') as file:
            pickle.dump(self.collision_animations, file)

    def get_gripper_joints(self, arm='left'):
        from pybullet_tools.pr2_utils import get_gripper_joints
        return get_gripper_joints(self.body, arm)

    def _close_cloned_gripper(self, gripper_cloned, arm):
        joints = get_cloned_gripper_joints(gripper_cloned)
        set_joint_positions(gripper_cloned, joints, [0] * 4)

    def _open_cloned_gripper(self, gripper_cloned, arm, width=0.548):
        joints = get_cloned_gripper_joints(gripper_cloned)
        set_joint_positions(gripper_cloned, joints, [width] * 4)

    def get_carry_conf(self, arm, grasp_type, g):
        return TOP_HOLDING_LEFT_ARM
        # if grasp_type == 'top':
        #     return TOP_HOLDING_LEFT_ARM
        # if grasp_type == 'side':
        #     return SIDE_HOLDING_LEFT_ARM

    def get_approach_vector(self, arm, grasp_type, scale=1):
        return tuple(scale * APPROACH_DISTANCE * 1.3 * get_unit_vector([0, 0, -1]))
        # if grasp_type == 'top':
        #     return APPROACH_DISTANCE*get_unit_vector([1, 0, 0])
        # if grasp_type == 'side':
        #     return APPROACH_DISTANCE*get_unit_vector([2, 0, -1])

    # def get_joints_from_group(self, joint_group):
    #     from pybullet_tools.pr2_utils import get_arm_joints, get_group_joints
    #     if joint_group == BASE_GROUP:
    #         joints = self.joints
    #     elif joint_group == BASE_TORSO_GROUP:
    #         joints = get_group_joints(self.body, joint_group)
    #     else: ## if joint_group == 'left':
    #         joints = get_arm_joints(self.body, joint_group)
    #     return joints

    def get_custom_limits(self):
        custom_limits = get_base_custom_limits(self.body, self.custom_limits)
        return custom_limits

    def randomly_spawn(self):
        def sample_robot_conf():
            (x1, y1, z1), (x2, y2, z2) = self.spawn_range
            x = random.uniform(x1, x2)
            y = random.uniform(y1, y2)
            yaw = random.uniform(0, math.pi)
            if self.use_torso:
                z1 = max(z1, 0)
                z2 = min(z2, 0.35)
                z = random.uniform(z1, z2)
                return [x, y, z, yaw]
            return [x, y, yaw]

        self.set_positions(sample_robot_conf(), self.get_base_joints())

    def get_tool_link(self, arm):
        return PR2_TOOL_FRAMES[arm]

    def get_gripper_root(self, arm):
        return PR2_GRIPPER_ROOTS[arm]

    def check_reachability(self, body, state, verbose=False, visualize=False, debug=False,
                           max_attempts=10, fluents=[]):
        from pybullet_tools.pr2_primitives import Pose
        from pybullet_tools.mobile_streams import get_ik_gen_old, get_ik_fn_old
        from world_builder.entities import Object

        if is_darwin():
            return True

        title = f'          robot.check_reachability for {body}'
        obj = body
        if isinstance(body, Object):
            title += f'({body.body})'
            body = body.body

        start = time.time()
        if verbose:
            print(f'... started {title}', end='\r')

        # context_saver = WorldSaver(bodies=[state.world.robot])
        arm = self.arms[0]
        q = self.get_base_conf()
        aq = self.get_arm_conf('left')
        p = Pose(body, get_pose(body))
        movable_poses = [(f[1], f[2]) for f in fluents if f[0] == 'AtPose']
        if debug:
            for b2, p2 in movable_poses:
                print(f'       {b2} {state.world.BODY_TO_OBJECT[b2].name}\t {p2}')
            # print('       ik_gen debug bottle')
            # p.assign()
            # set_camera_target_body(body)
            # wait_unlocked()

        def restore(result):
            # context_saver.restore()
            # remove_body(state.gripper)
            # state.gripper = None
            q.assign()
            aq.assign()
            p.assign()
            if verbose:
                print(f'... finished {title} -> {result} in {round(time.time() - start, 2)}s')

        with LockRenderer(True):
            funk = get_grasp_list_gen(state, verbose=verbose, visualize=visualize, top_grasp_tolerance=PI / 4)
            test = None
            outputs = funk(obj)

            kwargs = dict(collisions=True, teleport=False)
            funk2 = get_ik_gen_old(state, max_attempts=max_attempts, ir_only=True, learned=False,
                                   custom_limits=state.robot.custom_limits,
                                   verbose=verbose, visualize=visualize, **kwargs)

            funk3 = get_ik_fn_old(state, verbose=verbose, visualize=visualize, **kwargs)
            for (grasp, ) in outputs:
                ## test_approach_path
                result = True
                for b2, p2 in movable_poses:
                    if test is None:
                        test = get_cfree_approach_pose_test(state)
                    result = test(body, p, grasp, b2, p2)
                    if body not in self.possible_obstacles:
                        self.possible_obstacles[body] = set()
                    if not result:
                        self.possible_obstacles[body].add(b2)
                    elif b2 in self.possible_obstacles[body]:
                        self.possible_obstacles[body].remove(b2)
                    if debug:
                        print(title, f'| test_approach_path({body}, {b2})', result)
                if not result:
                    continue

                ## find bconf
                gen = funk2(arm, body, p, grasp)
                try:
                    result = next(gen)
                    if result is not None:
                        (bconf,) = result
                        ## find aconf
                        result = funk3(arm, body, p, grasp, bconf, fluents=fluents)
                        if result is not None:
                            if verbose:
                                print(title, f'succeeded', bconf)

                            if debug and False:
                                answer = query_yes_no(f"play reachability test traj?", default='no')
                                if answer:
                                    (cmd,) = result
                                    bconf.assign()
                                    attachment = grasp.get_attachment(self, arm, visualize=False)
                                    play_trajectory(cmd, p=p, attachment=attachment)

                            restore(True)
                            return True
                        else:
                            if verbose:
                                print(title, f'IK failed')
                except Exception:
                    if verbose:
                        print(title, f'IR failed')
                    pass

            restore(False)
            return False

    def check_reachability_space(self, body_link, state, body=None, fluents=[], num_samples=5, **kwargs):

        for f in fluents:
            if f[0].lower() == 'atposition':
                f[2].assign()

        ## sample three poses of cabbage and check reachability of each
        obj = None
        if body is None:
            body, path = load_asset('VeggieCabbage')[:2]
            obj = state.world.add_body(body, 'marker', path=path)

        if 'space' in state.world.get_type(body_link):
            funk = get_contain_list_gen(state, verbose=False, num_samples=num_samples)
        else:
            funk = get_stable_list_gen(state, verbose=False, num_samples=num_samples)
        outputs = funk(body, body_link)
        result = False
        for j in range(len(outputs)):
            if outputs is None or outputs[j] is None:
                print('\ncheck_reachability_space | outputs', outputs, '\n')
                continue
            set_pose(body, outputs[j][0].value)
            result = result or self.check_reachability(body, state, fluents=fluents, **kwargs)
            if result:
                break

        if not result and body in self.possible_obstacles:
            self.possible_obstacles[body_link] = self.possible_obstacles[body]

        if obj is not None:
            state.world.remove_object(obj)
        return result

    def plan_joint_motion(self, start_conf, end_conf, mp_fn, attachments, arm, pose=None,
                          verbose=False, title='robot.plan_joint_motion', debug=False, **kwargs):
        from pybullet_tools.utils import BodySaver
        from pybullet_tools.pr2_utils import get_arm_joints
        from pybullet_tools.pr2_primitives import create_trajectory, Commands, State

        def debug_trajectory(grasp_path, **kwargs):
            attachment = list(attachments.values())[0] if len(attachments) else None
            mt = create_trajectory(robot, arm_joints, grasp_path)
            cmd = Commands(State(attachments=attachments), savers=[BodySaver(robot)], commands=[mt])
            play_trajectory(cmd, p=pose, attachment=attachment, **kwargs)

        robot = self
        obss = kwargs['obstacles']
        arm_joints = get_arm_joints(robot, arm)
        set_joint_positions(robot, arm_joints, start_conf)
        grasp_path = mp_fn(robot, arm_joints, end_conf, attachments=attachments.values(), **kwargs)
        if grasp_path is None:
            if debug:
                ## try again without attachments, just for debugging purposes
                set_joint_positions(robot, arm_joints, start_conf)
                grasp_path = mp_fn(robot, arm_joints, end_conf, attachments=[], **kwargs)
                reason = 'robot-world collision'
                if grasp_path is not None:
                    reason = 'object-world collision'
                    ## replay the grasp path to find colliding objects
                    debug_trajectory(grasp_path, obstacles=obss, title='investigate path collision')

                if verbose:
                    print(f'{title}path planning failure because of {reason}')
                    wait_unlocked()
            return None
        if debug:
            kwargs = dict(obstacles=obss, title='successfully found path')
            if len(attachments) == 0:
                debug_trajectory(grasp_path, **kwargs)
            else:
                debug_trajectory(grasp_path[::-1], **kwargs)
        return grasp_path

    def compute_grasp_aconf(self, arm, obj, pose, grasp, custom_limits={}, grasp_conf_tries=10,
                           verbose=False, title='robot.sample_grasp_aconf', **collided_kwargs):
        from pybullet_tools.ikfast.pr2.ik import pr2_inverse_kinematics
        key = (arm, obj, grasp)
        if key in self.grasp_aconfs:
            print(f'grasp_conf found', key)
            return self.grasp_aconfs[key]
        robot = self
        pose_value = grasp.value

        tool_from_root = self.get_tool_from_root(arm)
        gripper_pose = multiply(robot.get_grasp_pose(pose.value, pose_value, body=obj), invert(tool_from_root))

        grasp_conf = pr2_inverse_kinematics(robot, arm, gripper_pose, custom_limits=custom_limits) #, upper_limits=USE_CURRENT)
                                                #nearby_conf=USE_CURRENT) # upper_limits=USE_CURRENT,

        count_down = grasp_conf_tries
        while (grasp_conf is None) or collided(robot, **collided_kwargs):
            if verbose:
                if grasp_conf is not None:
                    grasp_conf = nice(grasp_conf)
                print(
                    f'{title}Grasp IK failure | {grasp_conf} <- pr2_inverse_kinematics({robot}, '
                    f'{arm}, {nice(gripper_pose[0])}) | pose {pose}, grasp {grasp}')
            if count_down == 0:
                #if grasp_conf is not None:
                #    print(grasp_conf)
                #    #wait_if_gui()

                return None
            grasp_conf = pr2_inverse_kinematics(robot, arm, gripper_pose, custom_limits=custom_limits)
            count_down -= 1

        if verbose:
            print(f'{title}Grasp IK success | {nice(grasp_conf)} = pr2_inverse_kinematics({robot} '
                  f'{arm}, {nice(gripper_pose[0])}) | pose = {pose}, grasp = {grasp}')
        print(f'grasp_conf after', key, grasp_conf)
        self.grasp_aconfs[key] = grasp_conf
        return grasp_conf

    # def inverse_kinematics(self, arm, gripper_pose, obstacles, attempts=10, verbose=True, visualize=False):
    #     from pybullet_tools.ikfast.pr2.ik import pr2_inverse_kinematics
    #     return pr2_inverse_kinematics(self.body, arm, gripper_pose, custom_limits=self.custom_limits)


## -------------------------------------------------------------------------


from pybullet_tools.flying_gripper_utils import FEG_TOOL_LINK, FEG_JOINT_GROUPS, PANDA_FINGERS_GROUP, \
    SE3_GROUP, FEG_ARM_NAME, se3_ik, get_se3_joints, set_cloned_se3_conf, plan_se3_motion, get_se3_conf


class FEGripper(RobotAPI):

    arms = ['hand']
    grasp_types = ['hand']
    joint_group_names = ['hand']
    joint_groups = FEG_JOINT_GROUPS
    tool_from_hand = Pose(euler=Euler(math.pi / 2, 0, -math.pi / 2))
    finger_link = 8  ## for detecting if a grasp is pointing upwards
    cloned_finger_link = 7

    # def get_pose(self):
    #     from pybullet_tools.flying_gripper_utils import get_se3_conf
    #     return get_se3_conf(self.body)

    def create_gripper(self, arm='hand', visual=True, color=None):
        from pybullet_tools.utils import unit_pose
        gripper = clone_body(self.body, visual=False, collision=True)
        self.grippers[arm] = gripper
        set_pose(gripper, unit_pose())
        if not visual:
            set_all_color(gripper, TRANSPARENT)
        if color is not None:
            set_all_color(gripper, color)
        return gripper

    def remove_gripper(self, arm="hand"):
        if arm in self.grippers:
            self.grippers.pop(arm)

    def get_gripper_joints(self, arm=None):
        return get_joints_by_names(self.body, PANDA_FINGERS_GROUP)

    def _open_cloned_gripper(self, gripper, arm, width=1):
        from pybullet_tools.flying_gripper_utils import open_cloned_gripper
        open_cloned_gripper(self.body, gripper, w=width)

    def _close_cloned_gripper(self, gripper, arm):
        from pybullet_tools.flying_gripper_utils import close_cloned_gripper
        close_cloned_gripper(self.body, gripper)

    # def compute_grasp_width(self, arm, body_pose, grasp, body=None, verbose=False, **kwargs):
    #     from pybullet_tools.flying_gripper_utils import se3_ik, set_se3_conf, get_se3_conf
    #
    #     if isinstance(body, tuple):
    #         return 0.02
    #         # body = body[0]
    #
    #     # with PoseSaver(body):
    #     # weiyu debug: this should be not be unit pose, since grasp is with respect to the object
    #     # body_pose = unit_pose()
    #     grasp = grasp.value
    #     grasp_pose = multiply(body_pose, grasp)
    #     if verbose:
    #         print(f'robots.compute_grasp_width | body_pose = {nice(body_pose)} | grasp = {nice(grasp)}')
    #         print('robots.compute_grasp_width | grasp_pose = multiply(body_pose, grasp) = ', nice(grasp_pose))
    #
    #     with ConfSaver(self.body):
    #         with PoseSaver(body):
    #             conf = se3_ik(self, grasp_pose, verbose=False)
    #             if conf is None:
    #                 print('\t\t\tFEGripper.conf is None', nice(grasp))
    #                 return None
    #             # print('\tFEGripper.compute_grasp_width', nice(grasp))
    #             gripper = self.body
    #             set_se3_conf(gripper, conf)
    #             body_pose = self.get_body_pose(body_pose, body=body, verbose=verbose)
    #             set_pose(body, body_pose)
    #             if verbose:
    #                 print(f'robots.compute_grasp_width | gripper_grasp {gripper} | object_pose {nice(body_pose)}'
    #                       f' | se_conf {nice(get_se3_conf(gripper))} | grasp = {nice(grasp)} ')
    #
    #             # draw_pose(grasp_pose)
    #
    #             gripper_joints = self.get_gripper_joints()
    #             width = close_until_collision(gripper, gripper_joints, bodies=[body], **kwargs)
    #             # remove_body(gripper)
    #     return width

    def visualize_grasp(self, body_pose, grasp, arm='hand', color=GREEN, width=1,
                        body=None, verbose=False, new_gripper=False, mod_target=None):

        title = 'robots.visualize_grasp |'

        gripper = self.load_gripper(arm, color=color, new_gripper=new_gripper)
        self.open_cloned_gripper(gripper, arm, width)

        body_pose = self.get_body_pose(body_pose, body=body, verbose=verbose)
        grasp_pose = multiply(body_pose, grasp)

        if verbose:
            handles = draw_pose(grasp_pose, length=0.05)
            print(f'{title} body_pose = {nice(body_pose)} | grasp = {nice(grasp)}')
            print(f'{title} grasp_pose = multiply(body_pose, grasp) = ', nice(grasp_pose))

        grasp_conf = se3_ik(self, grasp_pose, verbose=verbose, mod_target=mod_target)

        if verbose and grasp_conf is None:
            print(f'{title} body_pose = {nice(body_pose)} --> ik failed')

        if verbose:
            remove_handles(handles)
        if grasp_conf is None:
            return None

        # set_pose(self.body, grasp_pose) ## wrong!
        set_cloned_se3_conf(self.body, gripper, grasp_conf)

        # set_camera_target_body(gripper, dx=0.5, dy=0.5, dz=0.5)
        return gripper

    def mod_grasp_along_handle(self, grasp, dl):
        return multiply(grasp, Pose(point=(dl, 0, 0)))

    def get_approach_vector(self, arm, grasp_type, scale=1):
        return APPROACH_DISTANCE/3 * get_unit_vector([0, 0, -1]) * scale

    def get_init(self, init_facts=[], conf_saver=None):
        robot = self.body

        def get_conf(joints):
            if conf_saver is None:
                return get_se3_conf(robot)
            return [conf_saver.conf[conf_saver.joints.index(n)] for n in joints]

        def get_se3_q():
            joints = get_se3_joints(robot)
            initial_q = Conf(robot, joints, get_conf(joints))
            for fact in init_facts:
                if fact[0] == 'seconf' and equal(fact[1].values, initial_q.values):
                    return fact[1]
            return initial_q

        initial_q = get_se3_q()
        arm = FEG_ARM_NAME
        return [('SEConf', initial_q), ('AtSEConf', initial_q), ('OriginalSEConf', initial_q),
                ('Arm', arm), ('Controllable', arm), ('HandEmpty', arm), ('CanMoveBase',)]

    def get_tool_link(self, arm):
        return FEG_TOOL_LINK

    def get_gripper_root(self, arm):
        return FEG_TOOL_LINK

    def get_tool_from_root(self, arm):
        return ((0, 0, -0.05), quat_from_euler((math.pi / 2, -math.pi / 2, -math.pi)))

    def get_carry_conf(self, arm, grasp_type, g):
        return g

    def get_all_joints(self):
        return SE3_GROUP + PANDA_FINGERS_GROUP

    def get_lisdf_string(self):
        return """
    <include name="{name}">
      <uri>../../pybullet_planning/models/franka_description/robots/hand_se3.urdf</uri>
      {pose_xml}
    </include>
"""

    def get_positions(self, joint_group='hand', roundto=None):
        return tuple([round(n, roundto) for n in get_se3_conf(self)])

    def iterate_approach_path(self, arm, gripper, pose_value, grasp, obstacles=[], body=None):
        from pybullet_tools.flying_gripper_utils import get_approach_path
        path = get_approach_path(self, body, grasp, obstacles=obstacles, custom_limits=self.custom_limits)
        if path is None:
            return
        for conf in path:
            set_cloned_se3_conf(self.body, gripper, conf.values)
            yield

    def get_stream_map(self, problem, collisions, custom_limits, teleport, domain_pddl=None, **kwargs):
        if basename(domain_pddl) == 'feg_kitchen_clean.pddl':
            from nsplan_tools.feg_streams import get_stream_map
        else:
            from pybullet_tools.flying_gripper_agent import get_stream_map
        return get_stream_map(problem, collisions, custom_limits, teleport, **kwargs)

    def get_stream_info(self):
        from pybullet_tools.flying_gripper_agent import get_stream_info
        # from pybullet_tools.pr2_agent import get_stream_info
        return get_stream_info()

    def get_base_joints(self):
        return get_se3_joints(self.body)

    def randomly_spawn(self):
        def sample_robot_conf():
            (x1, y1, z1), (x2, y2, z2) = self.spawn_range
            x = random.uniform(x1, x2)
            y = random.uniform(y1, y2)
            z = random.uniform(z1, z2)
            # yaw = random.uniform(0, math.pi)
            return [x, y, z, 0, -math.pi / 2, 0]

        self.set_positions(sample_robot_conf(), self.get_base_joints())

    def get_initial_q(self):
        init_q = get_joint_positions(self.body, self.get_base_joints())
        # init_q = get_joint_positions(self.body, self.get_base_joints())[:-1]
        # init_q = list(init_q) + [0] * 3
        return init_q

    def check_reachability(self, body, state, fluents=[], obstacles=None, verbose=False, debug=False):

        return True

        if obstacles is None:
            obstacles = state.obstacles
        if body in obstacles:
            obstacles = copy.deepcopy(obstacles)
            obstacles.remove(body)

        robot = self.body
        world = state.world
        init_q = self.get_initial_q()
        funk = get_grasp_list_gen(state, collisions=True, visualize=False,
                                  retain_all=False, top_grasp_tolerance=math.pi / 4)

        result = False
        body_pose = get_pose(body)
        outputs = funk(body)
        for output in outputs:
            grasp = output[0]
            w = grasp.grasp_width
            gripper_grasp = self.visualize_grasp(body_pose, grasp.value, body=grasp.body, color=GREEN, width=w)
            end_q = get_cloned_se3_conf(robot, gripper_grasp)
            if not collided(gripper_grasp, obstacles, verbose=True, tag='check reachability of movable', world=world):
                if verbose: print('\n... check reachability from', nice(init_q), 'to', nice(end_q))
                path = plan_se3_motion(self, init_q, end_q, obstacles=obstacles,
                                       custom_limits=self.custom_limits)
                if path is not None:
                    if verbose: print('... path found of length', len(path))
                    result = True
                    break
                else:
                    if verbose: print('... no path found', nice(end_q))
            else:
                if verbose: print('... collided', nice(end_q))
            remove_body(gripper_grasp)
        return result

    def check_reachability_space(self, body_link, state, fluents=[], obstacles=None, verbose=False):

        if obstacles is None:
            obstacles = state.obstacles
        for f in fluents:
            if f[0].lower() == 'atposition':
                f[2].assign()

        robot = self.body
        init_q = self.get_initial_q()
        q = Conf(robot, get_se3_joints(robot), init_q)
        marker = self.create_gripper(color=YELLOW)
        set_cloned_se3_conf(robot, marker, [0] * 6)

        funk = get_contain_list_gen(state, verbose=False, visualize=True)
        gen = funk(marker, body_link)
        count = 4
        result = False
        for output in gen:
            if output is None:
                break
            p = output[0].value
            (x, y, z), quat = p
            end_q = list([x, y, z + 0.1]) + list(euler_from_quat(quat))
            path = plan_se3_motion(robot, init_q, end_q, obstacles=obstacles,
                                   custom_limits=self.custom_limits)
            if verbose: print('\n... check reachability from', nice(init_q), 'to space', nice(end_q))
            if path is not None:
                if verbose: print('... path found of length', len(path))
                result = True
                break
            else:
                if verbose: print('... no path found', nice(end_q))

            if count == 0:
                break
            count -= 1

        remove_body(marker)
        q.assign()
        return result

