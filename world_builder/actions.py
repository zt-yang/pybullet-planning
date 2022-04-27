import numpy as np
import pybullet as p
import copy

from pybullet_tools.bullet_utils import clip_delta, multiply2d, is_above, nice, open_joint, set_camera_target_robot, \
    toggle_joint, add_attachment, remove_attachment
from pybullet_tools.pr2_streams import Position

from pybullet_tools.utils import str_from_object, get_closest_points, INF, create_attachment, wait_if_gui, \
    get_aabb, get_joint_position, get_joint_name, get_link_pose, link_from_name, PI, Pose, Euler, \
    get_extend_fn, get_joint_positions, set_joint_positions, get_max_limit, get_pose, set_pose, set_color, \
    remove_body, create_cylinder, set_all_static, wait_for_duration
from pybullet_tools.pr2_utils import PR2_TOOL_FRAMES, get_gripper_joints
from pybullet_tools.pr2_primitives import Trajectory, Command

from .world import State

class Action(object): # TODO: command
    def transition(self, state):
        raise NotImplementedError()
    def __repr__(self):
        return '{}{}'.format(self.__class__.__name__, str_from_object(self.__dict__))


class RobotAction(object):
    def __init__(self, robot):
        self.robot = robot


#######################################################


class TeleportAction(Action):
    def __init__(self, conf):
        self.conf = conf
    def transition(self, state):
        joints = state.robot.get_joints()  ## all joints, not just x,y,yqw
        if len(self.conf) == len(joints):
            state.robot.set_positions(self.conf, joints = joints)
        else:
            state.robot.set_pose(self.conf)
        set_camera_target_robot(state.robot)
        return state.new_state()


class MoveAction(Action):
    #def __init__(self, delta_x=0., delta_y=0., delta_yaw=0.):
    def __init__(self, delta): # TODO: pass in the robot
        # TODO: clip or normalize if moving too fast?
        self.delta = delta
    def transition(self, state):
        if self.delta is None:
            return state
        # TODO: could move to the constructor instead
        #new_delta = self.delta
        new_delta = clip_delta(self.delta, state.world.max_velocities, state.world.time_step)
        if not np.allclose(self.delta, new_delta, atol=0., rtol=1e-6):
            print('Warning! Clipped delta from {} to {}'.format(np.array(self.delta), np.array(new_delta)))

        assert len(new_delta) == len(state.robot.joints)
        conf = np.array(state.robot.get_positions())
        new_conf = multiply2d(conf, new_delta)
        # new_conf = [wrap_angle(position) for joint, position in zip(robot.joints, new_conf)]
        state.robot.set_positions(new_conf)
        return state.new_state()


class MoveArmAction(Action):
    def __init__(self, conf):
        self.conf = conf
    def transition(self, state):
        set_joint_positions(state.robot, self.conf.joints, self.conf.values)
        return state.new_state()

class MoveBaseAction(MoveArmAction):
    pass

#######################################################


class DriveAction(MoveAction):
    def __init__(self, delta=0.):
        super(DriveAction, self).__init__(delta=[delta, 0, 0])


class TurnAction(MoveAction):
    def __init__(self, delta=0.):
        super(TurnAction, self).__init__(delta=[0, 0, delta])


#######################################################


class AttachAction(Action):
    attach_distance = 5e-2
    def transition(self, state):
        new_attachments = dict(state.attachments)
        for obj in state.movable:
            collision_infos = get_closest_points(state.robot, obj, max_distance=INF)
            min_distance = min([INF] + [info.contactDistance for info in collision_infos])
            if (obj not in new_attachments) and (min_distance < self.attach_distance):
                attachment = create_attachment(state.robot, state.robot.base_link, obj)
                new_attachments[obj] = attachment
        return state.new_state(attachments=new_attachments)


class ReleaseAction(Action):
    def transition(self, state):
        return state.new_state(attachments={})


######################## Teleop Agent ###############################


class FlipAction(Action):
    # TODO: parent action
    def __init__(self, switch): #, active=True):
        self.switch = switch
        #self.active = active
    def transition(self, new_state):
        if not any(is_above(robot, get_aabb(self.switch)) for robot in new_state.robots):
            return new_state
        new_state.variables['Pressed', self.switch] = not new_state.variables['Pressed', self.switch]
        return new_state


class PressAction(Action):
    def __init__(self, button):
        self.button = button
    def transition(self, new_state):
        # TODO: automatically pass a copy of the state
        if not any(is_above(robot, get_aabb(self.button)) for robot in new_state.robots):
            return new_state
        new_state.variables['Pressed', self.button] = True
        return new_state

class OpenJointAction(Action):
    def __init__(self, affected):
        self.affected = affected
    def transition(self, state):
        for body, joint in self.affected:
            old_pose = get_joint_position(body, joint)
            toggle_joint(body, joint)
            new_pose = get_joint_position(body, joint)
            obj = state.world.BODY_TO_OBJECT[(body, joint)]
            print(f'{(body, joint)} | {obj.name} | limit: {nice((obj.min_limit, obj.max_limit))} | pose: {old_pose} -> {new_pose}')
        return state.new_state()

class PickUpAction(Action):
    def __init__(self, object, gripper='left'):
        self.object = object
        self.gripper = gripper
    def transition(self, state):
        obj = self.object
        tool_link = PR2_TOOL_FRAMES[self.gripper]
        tool_pose = get_link_pose(state.robot, link_from_name(state.robot, tool_link))
        old_pose = obj.get_pose()
        obj.set_pose(tool_pose)
        new_pose = obj.get_pose()
        print(f"{obj.name} is teleported from {nice(old_pose)} to {self.gripper} gripper {nice(new_pose)}")

        state.robot.objects_in_hand[self.gripper] = obj
        new_attachments = add_attachment(state=state, obj=obj, attach_distance=0.1)
        return state.new_state(attachments=new_attachments)

class PutDownAction(Action):
    def __init__(self, surface, gripper='left'):
        self.surface = surface
        self.gripper = gripper
    def transition(self, state):
        obj = state.robot.objects_in_hand[self.gripper]
        state.robot.objects_in_hand[self.gripper] = -1
        print(f'DEBUG1, PutDownAction transition {obj}')
        self.surface.place_obj(obj)
        new_attachments = remove_attachment(state, obj)
        return state.new_state(attachments=new_attachments)

OBJECT_PARTS = {
    'Veggie': ['VeggieLeaf', 'VeggieStem'],
    'Egg': ['EggFluid', 'EggShell']
} ## object.category are all lower case
OBJECT_PARTS = {k.lower():v for k,v in OBJECT_PARTS.items()}

class ChopAction(Action):
    def __init__(self, object):
        self.object = object
    def transition(self, state):
        pose = self.object.get_pose()
        surface = self.object.supporting_surface
        for obj_name in OBJECT_PARTS[self.object.category]:
            part = surface.place_new_obj(obj_name)
            yaw = np.random.uniform(0, PI)
            part.set_pose(Pose(point=pose[0], euler=Euler(yaw=yaw)))
        state.world.remove_object(self.object)
        objects = state.objects
        objects.remove(self.object.body)
        return state.new_state(objects=objects)

class CrackAction(Action):
    def __init__(self, object, surface):
        self.object = object
        self.surface = surface
    def transition(self, state):
        pose = self.object.get_pose()

class ToggleSwitchAction(Action):
    def __init__(self, object):
        self.object = object

class InteractAction(Action):
    def transition(self, state):
        return state


######################## PR2 Agent ###############################

class TeleportObjectAction(Action):
    def __init__(self, arm, grasp, object):
        self.object = object
        self.arm = arm
        self.grasp = grasp
    def transition(self, state):
        old_pose = get_pose(self.object)
        link = link_from_name(state.robot, PR2_TOOL_FRAMES.get(self.arm, self.arm))
        set_pose(self.object, get_link_pose(state.robot, link))
        new_pose = get_pose(self.object)
        print(f"   [TeleportObjectAction] !!!! obj {self.object} is teleported from {nice(old_pose)} to {self.arm} gripper {nice(new_pose)}")
        return state.new_state()

class GripperAction(Action):
    def __init__(self, arm, position=None, extent=None, teleport=False):
        self.arm = arm
        self.position = position
        self.extent = extent  ## 1 means fully open, 0 means fully closed
        self.teleport = teleport

    def transition(self, state):
        robot = state.robot

        ## get width from extent
        if self.extent != None:
            gripper_joint = get_gripper_joints(robot, self.arm)[0]
            self.position = get_max_limit(robot, gripper_joint)

        joints = get_gripper_joints(robot, self.arm)
        start_conf = get_joint_positions(robot, joints)
        end_conf = [self.position] * len(joints)
        if self.teleport:
            path = [start_conf, end_conf]
        else:
            extend_fn = get_extend_fn(robot, joints)
            path = [start_conf] + list(extend_fn(start_conf, end_conf))
        for positions in path:
            set_joint_positions(robot, joints, positions)

        return state.new_state()

class AttachObjectAction(Action):
    def __init__(self, arm, grasp, object):
        self.arm = arm
        self.grasp = grasp
        self.object = object
    def transition(self, state):
        link = link_from_name(state.robot, PR2_TOOL_FRAMES.get(self.arm, self.arm))
        new_attachments = add_attachment(state=state, obj=self.object, parent=state.robot,
                                         parent_link=link, attach_distance=None)  ## can attach without contact
        return state.new_state(attachments=new_attachments)

class DetachObjectAction(Action):
    def __init__(self, arm, object):
        self.arm = arm
        self.object = object
    def transition(self, state):
        # print(f'bullet.actions | DetachObjectAction | remove {self.object} from state.attachment')
        new_attachments = remove_attachment(state, self.object)
        return state.new_state(attachments=new_attachments)

class JustDoAction(Action):
    def __init__(self, body):
        self.body = body
    def transition(self, state):
        label = self.__class__.__name__.lower().replace('just','').capitalize() + 'ed'
        if label.endswith('eed'): label = label.replace('eed', '')
        state.variables[label, self.body] = True
        state.world.BODY_TO_OBJECT[self.body].add_text(label)
        return state.new_state()

class JustClean(JustDoAction):
    def __init__(self, body):
        super(JustClean, self).__init__(body)

class JustCook(JustDoAction):
    def __init__(self, body):
        super(JustCook, self).__init__(body)

class JustSeason(JustDoAction):
    def __init__(self, body):
        super(JustSeason, self).__init__(body)

class JustServe(JustDoAction):
    def __init__(self, body):
        super(JustServe, self).__init__(body)

class JustSucceed(Action):
    def __init__(self):
        pass
    def transition(self, state):
        return state.new_state()

class MagicDisappear(Action):
    def __init__(self, body):
        self.body = body
    def transition(self, state):
        state.world.remove_object(state.world.BODY_TO_OBJECT[self.body])
        objects = copy.deepcopy(state.objects)
        if self.body in objects: objects.remove(self.body)
        return state.new_state(objects=objects)

class TeleportObject(Action):
    def __init__(self, body, pose):
        self.body = body
        self.pose = pose
    def transition(self, state):
        self.pose.assign()
        return state.new_state()

class ChangeJointPosition(Action):
    def __init__(self, position):
        self.position = position

    def transition(self, state):
        pst = self.position
        max_position = Position((pst.body, pst.joint), 'max')
        if pst.value == max_position:
            state.variables['Opened', (pst.body, pst.joint)] = True
        self.position.assign()
        return state.new_state()

class ChangeLinkColorEvent(Action):
    def __init__(self, body, color, link=None):
        self.body = body
        self.color = color
        self.link = link
    def transition(self, state):
        set_color(self.body, self.color, self.link)
        return state.new_state()

class CreateCylinderEvent(Action):
    def __init__(self, radius, height, color, pose):
        self.radius = radius
        self.height = height
        self.color = color
        self.pose = pose
        self.body = None
    def transition(self, state):
        objects = state.objects
        if self.body == None:
            self.body = create_cylinder(self.radius, self.height, color=self.color)
            objects.append(self.body)
            set_pose(self.body, self.pose)
            set_all_static()
            print(f'    bullet.actions.CreateCylinderEvent | {self.body} at {nice(self.pose)}')
        return state.new_state(objects=objects) ## we may include the new body in objects, becomes the new state for planning

class RemoveBodyEvent(Action):
    def __init__(self, body=None, event=None):
        self.body = body
        self.event = event
    def transition(self, state):
        body = None
        objects = state.objects
        if self.body != None:
            body = self.body
            remove_body(self.body)
        if self.event != None:
            body = self.event.body
        if body != None:
            remove_body(body)
            objects.remove(body)
            print(f'    bullet.actions.RemoveBodyEvent | {body}')
        return state.new_state(objects=objects)

#######################################################

def apply_actions(problem, actions, time_step=0.01):
    """ act out the whole plan and event in the world without observation/replanning """
    state_event = State(problem.world)
    for i, action in enumerate(actions):
        print(i, action)
        if isinstance(action, Command):
            print('\n\n\napply_actions found Command', action)
            import sys
            sys.exit()
        elif isinstance(action, Action):
            state_event = action.transition(state_event.copy())
        elif isinstance(action, list):
            for a in action:
                state_event = a.transition(state_event.copy())
        wait_for_duration(time_step)