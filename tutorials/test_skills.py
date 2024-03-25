from __future__ import print_function
import os
import random
import json
import shutil
import time
import math

import numpy as np
from os.path import join, abspath, dirname, isdir, isfile
from os import listdir

from pybullet_tools.utils import connect, draw_pose, unit_pose, link_from_name, load_pybullet, load_model, \
    sample_aabb, AABB, set_pose, quat_from_euler, HideOutput, get_aabb_extent, unit_quat, remove_body, \
    set_camera_pose, wait_unlocked, disconnect, wait_if_gui, create_box, get_aabb, get_pose, draw_aabb, multiply, \
    Pose, get_link_pose, get_joint_limits, WHITE, RGBA, set_all_color, RED, GREEN, set_renderer, add_text, \
    Point, set_random_seed, set_numpy_seed, reset_simulation, joint_from_name, \
    get_joint_name, get_link_name, dump_joint, set_joint_position, ConfSaver, pairwise_link_collision
from pybullet_tools.bullet_utils import nice, set_camera_target_body, \
    draw_fitted_box, get_hand_grasps, sample_random_pose, \
    open_joint, get_grasp_db_file, take_selected_seg_images, dump_json
from pybullet_tools.flying_gripper_utils import se3_ik, create_fe_gripper, set_se3_conf
from pybullet_tools.pr2_tests import visualize_grasps
from pybullet_tools.general_streams import get_grasp_list_gen, get_contain_list_gen, Position, \
    get_stable_list_gen, get_handle_grasp_gen, sample_joint_position_gen

from world_builder.world import State
from world_builder.loaders import create_house_floor, create_table, create_movable
from world_builder.loaders_partnet_kitchen import sample_kitchen_sink, sample_full_kitchen
from world_builder.world_utils import load_asset, get_instance_name, get_partnet_doors, get_partnet_spaces
from world_builder.world_utils import get_instances as get_instances_helper
from world_builder.asset_constants import MODEL_HEIGHTS, MODEL_SCALES

from robot_builder.robot_builders import build_skill_domain_robot

from tutorials.test_utils import get_test_world, load_body, get_instances, draw_text_label, \
    load_model_instance, get_model_path, get_y_gap
from tutorials.config import ASSET_PATH


DEFAULT_TEST = 'kitchen' ## 'blocks_pick'

seed = None
if seed is None:
    seed = random.randint(0, 10 ** 6 - 1)
set_random_seed(seed)
set_numpy_seed(seed)
print('Seed:', seed)

# ####################################


def test_texture(category, id):
    connect(use_gui=True, shadows=False, width=1980, height=1238)
    path = join(ASSET_PATH, 'models', category, id) ## , 'mobility.urdf'

    body = load_body(path, 0.2)
    set_camera_target_body(body, dx=0.5, dy=0.5, dz=0.5)
    set_camera_target_body(body, dx=0.5, dy=0.5, dz=0.5)

    # import untangle
    # content = untangle.parse(path).robot
    #
    # import xml.etree.ElementTree as gfg
    # root = gfg.Element("robot")
    # tree = gfg.ElementTree(content)
    # with open(path.replace('mobility', 'mobility_2'), "wb") as files:
    #     tree.write(files)

# ####################################


def test_robot_rotation(body, robot):
    pose = ((0.2,0.3,0), quat_from_euler((math.pi/4, math.pi/2, 1.2)))
    set_pose(body, pose)
    conf = se3_ik(robot, pose)
    set_se3_conf(robot, conf)
    set_camera_target_body(body, dx=0.5, dy=0.5, dz=0.5)


def test_spatial_algebra(body, robot):

    ## transformations
    O_T_G = ((0.5, 0, 0), unit_quat())
    O_R_G = ((0, 0, 0), quat_from_euler((0, -math.pi / 2, 0)))
    G = multiply(O_T_G, O_R_G)
    gripper = robot.create_gripper(color=RED)

    ## original object pose
    set_pose(body, unit_pose())
    set_camera_target_body(body, dx=0.5, dy=0.5, dz=0.5)
    W_X_G = multiply(get_pose(body), G)
    set_pose(gripper, W_X_G)
    set_camera_target_body(body, dx=0.5, dy=0.5, dz=0.5)

    ## new object pose given rotation
    # object_pose = ((0.4, 0.3, 0), quat_from_euler((-1.2, 0.3, 0)))
    object_pose = ((0, 0, 0), quat_from_euler((-1.2, 0, 0)))
    set_pose(body, object_pose)
    W_X_G = multiply(get_pose(body), G)
    draw_pose(W_X_G, length=0.3)
    set_pose(gripper, W_X_G)
    set_camera_target_body(gripper, dx=0.5, dy=0, dz=0.5)
    wait_if_gui()


def test_handle_grasps(robot, category, skip_grasps=False):
    from pybullet_tools.pr2_streams import get_handle_pose

    world = get_test_world(robot, draw_base_limits=False)
    problem = State(world)
    funk = get_handle_grasp_gen(problem, visualize=False)
    funk2 = sample_joint_position_gen()

    ## load fridge
    instances = get_instances(category)
    n = len(instances)
    i = 0
    locations = [(0, 2*n) for n in range(1, n+1)]
    set_camera_pose((4, 3, 2), (0, 3, 0.5))

    def create_marker(xy):
        if category.lower() in ['cabinettop']:
            marker = create_box(0.05, 0.05, 0.07, color=RED)
            set_pose(marker, Pose(Point(x=xy[0], y=xy[1], z=1.2)))

    create_marker((0, 0))

    for id in instances:
        xy = locations[i]
        path, body, _ = load_model_instance(category, id, location=xy)
        i += 1
        instance_name = get_instance_name(path)
        world.add_body(body, f'{category.lower()}#{id}', instance_name)
        set_camera_target_body(body, dx=1, dy=1, dz=1)\

        if 'doorless' in category.lower():
            continue
        create_marker(xy)

        draw_text_label(body, id)

        ## color links corresponding to semantic labels
        body_joints = get_partnet_doors(path, body)
        world.add_joints(body, body_joints)

        for body_joint in body_joints:

            ## a few other tests here
            if skip_grasps:
                ## --- open door smartly when doing relaxed heuristic feasibility checking
                # open_joint(body, body_joint[1], hide_door=True)

                ## --- sample open positions during planning
                # pstn1 = Position(body_joint)
                # for (pstn, ) in funk2(body_joint, pstn1):
                #     pstn.assign()
                #     wait_if_gui('Next?')

                ## --- normalize joint positions for PIGINet
                b, j = body_joint
                # set_joint_position(b, j, 1.57)
                pstn1 = Position(body_joint)
                dump_joint(b, j)
                print('     positions', pstn1.value)

            else:
                outputs = funk(body_joint)
                body_pose = get_handle_pose(body_joint)

                set_renderer(True)
                set_camera_target_body(body, dx=2, dy=1, dz=1)
                visualize_grasps(problem, outputs, body_pose, retain_all=True)
                set_camera_target_body(body, dx=2, dy=1, dz=1)

        wait_if_gui('Next?')

    set_camera_pose((8, 8, 2), (0, 8, 1))
    wait_if_gui('Finish?')
    disconnect()


def reload_after_vhacd(path, body, scale, id=None):
    from pybullet_tools.utils import process_urdf, TEMP_URDF_DIR

    pose = get_pose(body)
    remove_body(body)
    new_urdf_path = process_urdf(path)
    id_urdf_path = join(TEMP_URDF_DIR, f"{id}.urdf")
    os.rename(new_urdf_path, id_urdf_path)
    body = load_pybullet(id_urdf_path, scale=scale)
    set_pose(body, pose)
    return id_urdf_path, body


def test_placement_in(robot, category, movable_category='Food', movable_instance=None,
                      seg_links=False, gen_z=False, **kwargs):

    world = get_test_world(robot)
    problem = State(world)
    funk = get_contain_list_gen(problem, collisions=True, verbose=False, **kwargs)

    ## load fridge
    if movable_instance is None:
        movable_instances = get_instances(movable_category)
        movable_instance = random.choice(list(movable_instances.keys()))

    instances = get_instances(category)
    n = len(instances)
    i = 0
    locations = [(0, get_y_gap(category) * n) for n in range(1, n + 1)]
    set_camera_pose((4, 3, 2), (0, 3, 0.5))
    for id in instances:
        (x, y) = locations[i]
        path, body, scale = load_model_instance(category, id, location=(x, y))
        # new_urdf_path, body = reload_after_vhacd(path, body, scale, id=id)

        name = f'{category.lower()}#{id}'
        if category in ['MiniFridge', 'Fridge', 'Cabinet', 'Microwave']:
            name += '_storage'
        world.add_body(body, name, path=path)
        set_camera_target_body(body, dx=1, dy=0, dz=1)

        ## color links corresponding to semantic labels
        spaces = get_partnet_spaces(path, body)
        world.add_spaces(body, spaces, path=path)

        doors = get_partnet_doors(path, body)
        for door in doors:
            open_joint(door[0], door[1])
        set_renderer(True)

        """ test taking images of link segments """
        if seg_links:
            name = category.lower()
            img_dir = join(dirname(__file__), 'pb_images', name)
            os.makedirs(img_dir, exist_ok=True)

            indices = {body: name}
            indices.update({(b, None, l): f"{name}::{get_link_name(b, l)}" for b, _, l in spaces})
            indices.update({(b, j): f"{name}::{get_joint_name(b, j)}" for b, j in doors})
            take_selected_seg_images(world, img_dir, body, indices, dx=1.5, dy=0, dz=1)

        else:

            for body_link in spaces:
                x += 1
                # space = clone_body(body, links=body_link[-1:], visual=True, collision=True)
                # world.add_body(space, f'{category.lower()}#{id}-{body_link}')

                cabbage, path = load_asset(movable_category, x=x, y=y, z=0, yaw=0,
                                           random_instance=movable_instance)[:2]
                cabbage_name = f'cabbage#{i}-{body_link}'
                world.add_body(cabbage, cabbage_name, path=path)

                outputs = funk(cabbage, body_link)
                if gen_z:
                    container_z = get_pose(body)[0][2]
                    zs = [output[0].value[0][2] for output in outputs if output is not None]
                    zs = [z - container_z for z in zs]
                    mov_mobility = f"{movable_category}/{movable_instance}"
                    sur_mobility = f"{category}/{id}"
                    add_heights_to_pose_database(mov_mobility, sur_mobility, zs)
                    continue

                set_pose(cabbage, outputs[0][0].value)
                markers = []
                for j in range(1, len(outputs)):
                    marker = load_asset(movable_category, x=x, y=y, z=0, yaw=0,
                                        random_instance=movable_instance)[0]
                    markers.append(marker)
                    set_pose(marker, outputs[j][0].value)

                set_renderer(True)
                set_camera_target_body(cabbage, dx=1, dy=0, dz=1)
                wait_if_gui('Next space?')
                for m in markers:
                    remove_body(m)
                reset_simulation()
                set_renderer(True)
        i += 1
        reset_simulation()

    # set_camera_pose((4, 3, 2), (0, 3, 0.5))
    if not gen_z:
        wait_if_gui('Finish?')
    disconnect()


def test_placement_on(robot, category, surface_name=None, seg_links=False, gen_z=False,
                      movable_category='Food', movable_instance=None, **kwargs):

    world = get_test_world(robot)
    problem = State(world)
    funk = get_stable_list_gen(problem, collisions=True, verbose=False, **kwargs)

    if movable_instance is None:
        movable_instances = get_instances(movable_category)
        movable_instance = random.choice(list(movable_instances.keys()))

    ###########################################################

    if category == 'box' and gen_z:
        cabbage, path = load_asset(movable_category, x=0, y=0, z=0, yaw=0,
                                   random_instance=movable_instance)[:2]
        z = get_pose(cabbage)[0][2] - get_aabb(cabbage).lower[2]
        zs = [z] * 20

        mov_mobility = f"{movable_category}/{movable_instance}"
        sur_mobility = f"{category}"
        add_heights_to_pose_database(mov_mobility, sur_mobility, zs)
        return

    surface_links = {
        'BraiserBody': 'braiser_bottom',
        'Sink': 'sink_bottom',
    }
    if category in surface_links and surface_name is None:
        surface_name = surface_links[category]

    ## load fridges
    instances = get_instances(category)
    n = len(instances)
    i = 0
    locations = [(0, get_y_gap(category) * n) for n in range(2, n + 2)]
    set_camera_pose((4, 3, 2), (0, 3, 0.5))
    for id in instances:
        (x, y) = locations[i]
        path, body, scale = load_model_instance(category, id, location=(x, y))
        # new_urdf_path, body = reload_after_vhacd(path, body, scale, id=id)

        ## ---- add surface
        name = f'{category.lower()}#{id}'
        world.add_body(body, name, path=path)
        set_camera_target_body(body, dx=1, dy=0, dz=1)
        nn = category.lower()
        indices = {body: nn}
        if surface_name is not None:
            link = link_from_name(body, surface_name)
            print('radius', round( get_aabb_extent(get_aabb(body, link=link))[0]/ scale / 2, 3))
            print('height', round( get_aabb_extent(get_aabb(body))[2]/ scale / 2, 3))
            body = (body, None, link)
            world.add_body(body, name, path=path)
            indices[body] = f"{nn}::{surface_name}"

        """ test taking images of link segments """
        if seg_links:
            name = category.lower()
            img_dir = join(dirname(__file__), 'pb_images', name)
            os.makedirs(img_dir, exist_ok=True)
            take_selected_seg_images(world, img_dir, body[0], indices, dx=0.2, dy=0, dz=1)
            # wait_unlocked()

        else:
            ## ---- add many cabbages
            # space = clone_body(body, links=body_link[-1:], visual=True, collision=True)
            # world.add_body(space, f'{category.lower()}#{id}-{body_link}')
            x += 1
            cabbage, path = load_asset(movable_category, x=x, y=y, z=0, yaw=0,
                                       random_instance=movable_instance)[:2]
            cabbage_name = f'{movable_category}#{i}-{body}'
            world.add_body(cabbage, cabbage_name, path=path)

            outputs = funk(cabbage, body)
            if gen_z:
                if isinstance(body, tuple):
                    container_z = get_pose(body[0])[0][2]
                else:
                    container_z = get_pose(body)[0][2]
                zs = [output[0].value[0][2] for output in outputs if output is not None]
                zs = [z - container_z for z in zs]
                mov_mobility = f"{movable_category}/{movable_instance}"
                sur_mobility = f"{category}/{id}"
                add_heights_to_pose_database(mov_mobility, sur_mobility, zs)
                continue

            set_pose(cabbage, outputs[0][0].value)
            markers = []
            for j in range(1, len(outputs)):
                marker = load_asset(movable_category, x=x, y=y, z=0, yaw=0,
                                    random_instance=movable_instance)[0]
                markers.append(marker)
                set_pose(marker, outputs[j][0].value)

            set_renderer(True)
            set_camera_target_body(cabbage, dx=1, dy=0, dz=1)
            wait_if_gui('Next surface?')
            for m in markers:
                remove_body(m)
            reset_simulation()
        i += 1

    # set_camera_pose((4, 3, 2), (0, 3, 0.5))
    if not gen_z:
        wait_if_gui('Finish?')
    disconnect()


def test_gripper_joints():
    """ visualize ee link pose as conf changes """
    world = get_test_world(robot='feg')
    robot = world.robot

    set_se3_conf(robot, (0, 0, 0, 0, 0, 0))
    set_camera_target_body(robot, dx=0.5, dy=0.5, dz=0.5)
    for j in range(3, 6):
        limits = get_joint_limits(robot, j)
        values = np.linspace(limits[0], limits[1], num=36)
        for v in values:
            conf = [0, 0, 0, 0, math.pi/2, 0]
            conf[j] = v
            set_se3_conf(robot, conf)
            set_camera_target_body(robot, dx=0.5, dy=0.5, dz=0.5)
            time.sleep(0.1)

    wait_if_gui('Finish?')
    disconnect()


def test_gripper_range(IK=False):
    """ visualize all possible gripper orientation """
    world = get_test_world(robot='feg')
    robot = world.robot

    set_se3_conf(robot, (0, 0, 0, 0, 0, 0))
    set_camera_target_body(robot, dx=0.5, dy=0.5, dz=0.5)
    choices = np.linspace(-math.pi, math.pi, num=9)[:-1]
    bad = [choices[1], choices[3]]
    mi, ma = min(choices), max(choices)
    ra = ma - mi
    def get_color(i, j, k):
        color = RGBA((i-mi)/ra, (j-mi)/ra, (k-mi)/ra, 1)
        return color
    def mynice(tup):
        tup = nice(tup)
        if len(tup) == 2:
            return tup[-1]
        return tuple(list(tup)[-3:])
    for i in choices:
        for j in choices:
            for k in choices:
                if IK:
                    gripper = create_fe_gripper(init_q=[0, 0, 0, 0, 0, 0], POINTER=True)
                    pose = ((0,0,0), quat_from_euler((i,j,k)))
                    conf = se3_ik(robot, pose)
                    if conf == None:
                        remove_body(gripper)
                        print('failed IK at', nice(pose))
                        continue
                    else:
                        print('pose =', mynice(pose), '-->\t conf =', mynice(conf))
                        set_se3_conf(gripper, conf)
                        set_all_color(gripper, WHITE)
                        # if j in bad:
                        #     set_all_color(gripper, RED)
                        # else:
                        #     set_all_color(gripper, GREEN)
                else:
                    conf = [0, 0, 0, i, j, k]
                    gripper = create_fe_gripper(init_q=conf, POINTER=True)
                    set_all_color(gripper, WHITE)
                    pose = get_link_pose(gripper, link_from_name(gripper, 'panda_hand'))
                    print('conf =', mynice(conf), '-->\t pose =', mynice(pose))

                    # set_all_color(gripper, get_color(i,j,k))
            set_camera_target_body(robot, dx=0.5, dy=0.5, dz=0.5)
    set_camera_target_body(robot, dx=0.5, dy=0.5, dz=0.5)

    wait_if_gui('Finish?')
    disconnect()


def test_torso():
    world = get_test_world(robot='pr2')
    robot = world.robot
    torso_joint = joint_from_name(robot, 'torso_lift_joint')
    l = get_joint_limits(robot, torso_joint)
    robot.set_joint_positions([torso_joint], [1.5])
    print(l)
    # x, y, z, yaw = robot.get_positions('base-torso')
    # robot.set_positions_by_group('base-torso', (x, y, 0.9, yaw))
    wait_unlocked()
    print(robot)


def test_handle_grasps_counter(robot='pr2'):
    from world_builder.loaders import load_floor_plan

    connect(use_gui=True, shadows=False, width=1980, height=1238)
    draw_pose(unit_pose(), length=2.)

    # lisdf_path = join(ASSET_PATH, 'scenes', f'kitchen_lunch.lisdf')
    # world = load_lisdf_pybullet(lisdf_path, verbose=True)

    # world = World()
    world = get_test_world(robot, semantic_world=True, draw_base_limits=False)
    robot = world.robot
    floor = load_floor_plan(world, plan_name='counter.svg')
    # robot = build_skill_domain_robot(world, 'feg')

    world.summarize_all_objects()
    # state = State(world, grasp_types=robot.grasp_types)
    joints = world.cat_to_bodies('drawer')
    # joints = [(6, 1)]

    for body_joint in joints:
        obj = world.BODY_TO_OBJECT[body_joint]
        print(body_joint, obj.name)
        link = obj.handle_link
        body, joint = body_joint
        set_camera_target_body(body, link=link, dx=0.5, dy=0.5, dz=0.5)
        draw_fitted_box(body, link=link, draw_centroid=True)
        grasps = get_hand_grasps(world, body, link=link, visualize=False,
                                 retain_all=True, handle_filter=True, length_variants=True)
        set_camera_target_body(body, link=link, dx=0.5, dy=0.5, dz=0.5)

    wait_if_gui('Finish?')
    disconnect()


def test_placement_counter():
    from world_builder.loaders import load_floor_plan
    from world_builder.world import World

    connect(use_gui=True, shadows=False, width=1980, height=1238)
    draw_pose(unit_pose(), length=2.)

    surfaces = {
        'counter': {
            'back_left_stove': [],
            'back_right_stove': [],
            'front_left_stove': [],
            'front_right_stove': [],
            'hitman_tmp': [],
            'indigo_tmp': [],
        }
    }
    spaces = {
        'counter': {
            'sektion': [],
            'dagger': [],
            'hitman_drawer_top': [],
            # 'hitman_drawer_bottom': [],
            'indigo_drawer_top': [],
            # 'indigo_drawer_bottom': [],
            'indigo_tmp': []
        },
    }

    world = World()
    floor = load_floor_plan(world, plan_name='counter.svg', surfaces=surfaces, spaces=spaces)
    robot = build_skill_domain_robot(world, 'feg')

    world.open_all_doors_drawers()
    world.summarize_all_objects()
    state = State(world, grasp_types=robot.grasp_types)
    funk = get_grasp_list_gen(state, collisions=True, num_samples=3,
                              visualize=False, retain_all=False)

    surfaces = world.cat_to_bodies('surface')
    spaces = world.cat_to_bodies('space')
    regions = surfaces
    opened_poses = {}

    for rg in regions:
        r = world.BODY_TO_OBJECT[rg]
        draw_aabb(get_aabb(r.body, link=r.link))
        opened_poses[rg] = get_link_pose(r.body, r.link)

        if rg in surfaces:
            body = r.place_new_obj('OilBottle').body
            draw_fitted_box(body, draw_centroid=False)
            set_camera_target_body(body, dx=0.5, dy=0, dz=0)
            set_camera_target_body(body, dx=0.5, dy=0, dz=0)
            grasps = get_hand_grasps(world, body, visualize=True, retain_all=True)

        # if rg in spaces:
        #     body = r.place_new_obj('MeatTurkeyLeg').body
        #     draw_fitted_box(body, draw_centroid=False)
        #     set_camera_target_body(body, dx=0.1, dy=0, dz=0.5)
        #     set_camera_target_body(body, dx=0.1, dy=0, dz=0.5)
        #     # grasps = get_hand_grasps(world, body, visualize=False, retain_all=False)
        #
        #     outputs = funk(body)
        #     print(f'grasps on body {body}:', outputs)
        #     visualize_grasps(state, outputs, get_pose(body), retain_all=True, collisions=True)

        set_renderer(True)
        print(f'test_placement_counter | placed {body} on {r}')
    wait_if_gui('Finish?')
    disconnect()


def test_pick_place_counter(robot):
    from world_builder.loaders_partnet_kitchen import load_random_mini_kitchen_counter
    world = get_test_world(robot, semantic_world=True)
    load_random_mini_kitchen_counter(world)


def test_vhacd(category, visualize=False):
    from pybullet_tools.utils import process_urdf
    TEMP_OBJ_DIR = 'vhacd'
    instances = get_instances(category)
    if visualize:
        world = get_test_world()
        x, y = 0, 0

    instances = ['100021']

    for idx in instances:
        urdf_path = f'../../assets/models/{category}/{idx}/mobility.urdf'

        if visualize:
            body = load_pybullet(urdf_path)
            set_pose(body, ((x, y, 0), unit_quat()))

        new_urdf_path = process_urdf(urdf_path)

        if visualize:
            body = load_pybullet(new_urdf_path)
            set_pose(body, ((x+2, y, 0), unit_quat()))

            set_camera_target_body(body, dx=1, dy=1, dz=1)
            wait_unlocked()
            y += 2
        else:
            shutil.move(new_urdf_path, new_urdf_path.replace('mobility.urdf', f'{idx}.urdf'))
            shutil.move(TEMP_OBJ_DIR, urdf_path.replace('mobility.urdf', TEMP_OBJ_DIR))


def test_sink_configuration(robot, pause=False):
    world = get_test_world(robot=robot, semantic_world=True)
    floor = create_house_floor(world, w=10, l=10, x=5, y=5)
    target = None
    for x in range(1, 5):
        for y in range(1, 5):
            base = sample_kitchen_sink(world, floor=floor, x=2*x, y=2*y)[1]
            mx, my, mz = base.aabb().upper
            ny = base.aabb().lower[1]
            aabb = AABB(lower=(mx - 0.3, ny, mz), upper=(mx, my, mz + 0.1))
            draw_aabb(aabb)
            if x == 4 and y == 3:
                target = base
            if pause:
                set_camera_target_body(base, dx=0.1, dy=0, dz=1.5)
                wait_unlocked()
    set_camera_target_body(target, dx=2, dy=0, dz=4)
    wait_unlocked()


def test_kitchen_configuration(robot):
    world = get_test_world(robot=robot, semantic_world=True, initial_xy=(1.5, 4))
    sample_full_kitchen(world)


def test_reachability(robot):
    world = get_test_world(robot=robot, semantic_world=True, custom_limits=((-4, -4), (4, 4)))
    robot = world.robot
    state = State(world, grasp_types=robot.grasp_types)

    for w, xy in [(0.3, (0, 0)), (0.5, (2, 2))]:
        table1 = create_table(world, w=w, xy=xy)
        movable1 = create_movable(world, table1, xy=xy)
        result = robot.check_reachability(movable1, state)
        print('w', w, result)

    wait_unlocked()


def get_partnet_aabbs():
    world = get_test_world()
    draw_pose(unit_pose(), length=1.5)
    DATABASE_DIR = abspath(join(__file__, '..', '..', 'databases'))
    shape_file = join(DATABASE_DIR, 'partnet_shapes.json')

    skips = ['Kettle', 'Toaster', 'TrashCan', 'CabinetAboveOven', 'DeskStorage']
    categories = list(MODEL_SCALES.keys()) + list(MODEL_HEIGHTS.keys())
    skip_till = None
    if skip_till is not None:
        categories = categories[categories.index(skip_till)+1:]
    categories = [c for c in categories if c not in skips and c != c.lower()]
    shapes = {}  ## category: {id: (dlower, dupper)}
    # if isfile(shape_file):
    #     shapes = json.load(open(shape_file, 'r'))
    for category in categories:
        instances = get_instances(category)
        if category not in shapes:
            shapes[category] = {}
        bodies = []
        for idx in instances:
            path = join(ASSET_PATH, 'models', category, idx, 'mobility.urdf')
            if not isfile(path) or idx in shapes[category]:
                print('skipping', path)
                continue
            path, body, scale = load_model_instance(category, idx)
            set_pose(body, ([0, 0, 0], quat_from_euler([0, 0, math.pi])))

            aabb = get_aabb(body)
            shapes[category][idx] = (aabb.lower, aabb.upper)
            bodies.append(body)
        #     wait_for_duration(0.25)
        # wait_unlocked()
        for body in bodies:
            remove_body(body)
    with open(shape_file, 'w') as f:
        json.dump(shapes, f, indent=2, sort_keys=False)


############################################################################


def add_heights_to_pose_database(movable, surface, zs):
    from world_builder.world_utils import Z_CORRECTION_FILE as file
    from scipy.stats import norm
    if len(zs) == 0:
        print('         no samples for', movable, surface)
        return
    mina, maxa = min(zs), max(zs)
    while maxa - mina > 0.02:
        zs.remove(mina)
        zs.remove(maxa)
        print('       throwing away outliners', nice(mina), nice(maxa))
        mina, maxa = min(zs), max(zs)
    print('         length', len(zs))
    collection = json.load(open(file, 'r')) if isfile(file) else {}
    if movable not in collection:
        collection[movable] = {}
    mu, std = norm.fit(zs)
    collection[movable][surface] = [round(i, 6) for i in [mina, maxa, mu, std]]
    dump_json(collection, file, width=150)


def get_placement_z(robot='pr2'):
    from world_builder.world_utils import Z_CORRECTION_FILE as file
    kwargs = dict(num_samples=50, gen_z=True, learned_sampling=False)
    surfaces = ['box', 'Sink', 'Microwave', "OvenCounter"]
    storage = ['CabinetTop', 'MiniFridge']
    movables = {
        'Bottle': surfaces + storage,
        'Food': surfaces + storage + ['BraiserBody'],
        'Medicine': surfaces + storage + ['BraiserBody'],
        'BraiserLid': ['box'],
    }
    dic = json.load(open(file, 'r')) if isfile(file) else {}
    for mov, surfaces in movables.items():
        for sur in surfaces:
            num_sur_instances = len(get_instances(sur)) if sur != 'box' else 1
            for ins in get_instances(mov):
                mov_mibility = f"{mov}/{ins}"
                if mov_mibility in dic:
                    if sur == 'box' and sur in dic[mov_mibility]:
                        continue
                    elif len([i for i in dic[mov_mibility] if sur in i]) == num_sur_instances:
                        continue
                if sur in ['MiniFridge', 'CabinetTop']:
                    test_placement_in(robot, category=sur, movable_category=mov,
                                      movable_instance=ins, **kwargs)
                else:
                    test_placement_on(robot, category=sur, movable_category=mov,
                                      movable_instance=ins, **kwargs)


def test_tracik(robot, verbose=False):
    from pybullet_tools.tracik import IKSolver
    from robot_builder.spot_utils import solve_leg_conf
    world = get_test_world(robot=robot, width=1200, height=1200,
                           semantic_world=True, draw_origin=True,
                           custom_limits=((-3, -3), (3, 3)))
    robot = world.robot
    set_camera_target_body(robot.body, distance=0.5)
    set_joint_position(robot.body, joint_from_name(robot.body, 'arm0.f1x'), -1.5)
    # compute_link_lengths(robot.body)

    box = create_box(0.05, 0.05, 0.075, color=(1, 0, 0, 1))
    grasp_pose = ((0, 0, 0.2), quat_from_euler((0, math.pi/2, 0)))

    tool_link = robot.get_tool_link()
    body_solver = IKSolver(robot, tool_link=tool_link, first_joint='torso_lift_joint',
                           custom_limits=robot.custom_limits)  ## using 13 joints

    while True:
        box_pose = sample_random_pose(AABB(lower=[-0.3, -0.3, 0.2], upper=[0.3, 0.3, 1.2])) ## ((0, 0, 0.1), (0, 0, 0, 1))
        gripper_pose = multiply(box_pose, grasp_pose)
        print('\n', nice(gripper_pose))
        for conf in body_solver.generate(gripper_pose):
            joint_state = dict(zip(body_solver.joints, conf))
            joint_values = {}
            for i, value in joint_state.items():
                if i == 0:
                    continue
                joint_name = get_joint_name(robot.body, i)
                joint_values[i] = (joint_name, value)

            collided = False
            with ConfSaver(robot.body):
                body_solver.set_conf(conf)
                body_link = link_from_name(robot.body, 'body_link')
                for i in ['arm0.link_sh1', 'arm0.link_hr0', 'arm0.link_el0',
                          'arm0.link_el1', 'arm0.link_wr0', 'arm0.link_wr1']:
                    link = link_from_name(robot.body, i)
                    if pairwise_link_collision(robot.body, link, robot.body, body_link):
                        collided = True
                        break
            if collided:
                if verbose:
                    print('\n\n self-collision!')
                break

            leg_conf = solve_leg_conf(robot.body, joint_state[0], verbose=False)
            if leg_conf is None:
                if verbose:
                    print('\n\n failed leg ik!')
                break

            for i in range(len(leg_conf.values)):
                index = leg_conf.joints[i]
                value = leg_conf.values[i]
                joint_values[index] = (get_joint_name(robot.body, index), value)

            joint_values = dict(sorted(joint_values.items()))
            for i, (joint_name, value) in joint_values.items():
                print('\t', i, '\t', joint_name, '\t', round(value, 3))

            set_pose(box, box_pose)
            body_solver.set_conf(conf)
            leg_conf.assign()
            break


############################################################################


if __name__ == '__main__':

    """ ------------------------ object categories -------------------------
        Kitchen Movable: 'Bottle', 'Food', 'BraiserLid', 'Sink', 'SinkBase', 'Faucet',
        Kitchen Furniture: 'MiniFridge', 'KitchenCounter', 'MiniFridgeBase',
                            'OvenCounter', 'OvenTop', 'MicrowaveHanging', 'MiniFridgeBase',
                            'CabinetLower', 'CabinetTall', 'CabinetUpper', 'DishwasherBox'
        Kitchen Cooking: 'KitchenFork', 
        Packing:    'Stapler', 'Camera', 'EyeGlasses', 'Knife', 'Tray',
    ------------------------------------------------------------------------ """

    """ --- models related --- """
    # get_data(categories=['Cupboard'])
    # test_texture(category='CoffeeMachine', id='103127')
    # test_vhacd(category='BraiserBody')
    # get_partnet_aabbs()
    # get_placement_z()

    """ --- robot related  --- """
    robot = 'rummy'  ## 'spot' | 'feg' | 'pr2'
    # test_gripper_joints()
    # test_gripper_range()
    # test_torso()
    # test_reachability(robot)
    # test_tracik(robot)

    """ --- grasps and placement for articulated storage units --- 
        IN: 'MiniFridge', 'MiniFridgeDoorless', 'CabinetTop'
    """
    # test_handle_grasps(robot, category='CabinetTop', skip_grasps=True)
    # test_placement_in(robot, category='MiniFridge', seg_links=False,
    #                   movable_category='BraiserLid', learned_sampling=True)

    """ --- placement related for supporting surfaces --- 
        ON: 'KitchenCounter', 
            'Tray' (surface_name='tray_bottom'),
            'Sink' (surface_name='sink_bottom'),
            'BraiserBody' (surface_name='braiser_bottom'),
    """
    # test_placement_on(robot, category='BraiserBody', surface_name='braiser_bottom', seg_links=True)
    # test_placement_on(robot, category='Sink', surface_name='sink_bottom', seg_links=True)

    """ --- specific kitchen counter --- """
    # test_placement_counter()  ## initial placement
    # test_handle_grasps_counter()
    # test_pick_place_counter(robot)

    """ --- procedurally generated kitchen counters --- """
    # test_sink_configuration(robot, pause=True)
    # test_kitchen_configuration(robot)
