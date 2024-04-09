#!/usr/bin/env python
from __future__ import print_function
import os
from os.path import join, abspath, dirname, isdir, isfile
from os import listdir
import copy
import shutil

from pybullet_tools.utils import disconnect, reset_simulation, VideoSaver, wait_unlocked, timeout, set_renderer
from pybullet_tools.bullet_utils import get_datetime, initialize_logs

from lisdf_tools.lisdf_utils import pddlstream_from_dir
from lisdf_tools.lisdf_loader import load_lisdf_pybullet
from lisdf_tools.lisdf_planning import Problem

from world_builder.world import State, evolve_processes
from world_builder.world_generator import save_to_outputs_folder

from cogarch_tools.processes.pddlstream_agent import PDDLStreamAgent
from cogarch_tools.processes.teleop_agent import TeleOpAgent
from cogarch_tools.cogarch_utils import get_parser, init_pybullet_client, get_pddlstream_kwargs, clear_planning_dir, \
    get_pddlstream_problem, PROBLEM_CONFIG_PATH, reorg_output_dirs

from leap_tools.hierarchical_agent import HierarchicalAgent


SAVE_COLLISIONS = False


#######################################################


def run_agent(agent_class=HierarchicalAgent, config='config_dev.yaml', config_root=PROBLEM_CONFIG_PATH,
              create_robot_fn=None, problem=None, open_goal=None, domain=None, stream=None, viewer=True,
              exp_dir=None, exp_subdir=None, exp_name='default', reset=False,
              record_problem=True, save_testcase=False, record_plans=False, data_generation=False, use_rel_pose=False,
              domain_modifier=None, object_reducer=None, comparing=False, load_initial_state=False,
              window_width=1440, window_height=1120, **kwargs):
    """
    problem:    name of the problem builder function to solve
    exp_dir:    sub-directory in `bullet/experiments` to save the planning data
    exp_name:   for comparison groups of different algorithms, e.g. ['original', 'hpn', 'hpn_goal-related']
    comparing:  put solutions inside exp_dir/exp_name instead of inside exp_dir
    """

    from pybullet_tools.logging_utils import myprint

    initialize_logs()  ## everything would be loaded to txt log file

    if exp_subdir is None and isinstance(problem, str):
        exp_subdir = problem
    args = get_parser(config=config, config_root=config_root, viewer=viewer,
                      problem=problem, open_goal=open_goal,
                      exp_dir=exp_dir, exp_subdir=exp_subdir, exp_name=exp_name,
                      domain=domain, stream=stream, use_rel_pose=use_rel_pose,
                      record_problem=record_problem, save_testcase=save_testcase)
    if 'robot_builder_args' not in kwargs:
        kwargs['robot_builder_args'] = args.robot_builder_args
    kwargs['robot_builder_args']['create_robot_fn'] = create_robot_fn
    if hasattr(args, 'goal_variations'):
        kwargs['world_builder_args'] = {'goal_variations': args.goal_variations}

    """ load problem """
    if '/' in args.exp_subdir:
        world = load_lisdf_pybullet(args.exp_subdir, width=1440, height=1120, time_step=args.time_step)
        problem = Problem(world)
        pddlstream_problem = pddlstream_from_dir(
            problem, exp_dir=abspath(args.exp_dir), collisions=not args.cfree,
            teleport=args.teleport, replace_pddl=True, domain_name=domain, stream_name=stream)
        state = State(world)
        exogenous = []
        goals = pddlstream_problem[-1]
        subgoals = None
        skeleton = None
        problem_dict = {'pddlstream_problem': pddlstream_problem}

        """ sample problem """
    else:
        init_pybullet_client(args)
        state, exogenous, goals, problem_dict = get_pddlstream_problem(args, **kwargs)
        pddlstream_problem = problem_dict['pddlstream_problem']
        subgoals = problem_dict['subgoals']
        skeleton = problem_dict['skeleton']

    state.world.add_to_planning_config('config', config)
    state.world.add_to_planning_config('config_root', config_root)

    init = pddlstream_problem.init

    ## load next test problem
    if args.save_testcase:
        disconnect()
        return
    if load_initial_state:
        return state

    """ load planning agent """
    solver_kwargs = get_pddlstream_kwargs(args, skeleton, subgoals, [copy.deepcopy(state), goals, init])
    if SAVE_COLLISIONS:
        solver_kwargs['evaluation_time'] = 10
    # agent = TeleOpAgent(state.world)
    agent = agent_class(state.world, init=init, goals=goals, processes=exogenous, pddlstream_kwargs=solver_kwargs)
    agent.set_pddlstream_problem(problem_dict, state)

    # note = kwargs['world_builder_args'].get('note', None) if 'world_builder_args' in kwargs else None
    agent.init_experiment(args, domain_modifier=domain_modifier, object_reducer=object_reducer, comparing=comparing)

    ## for visualizing observation
    if hasattr(args, 'save_initial_observation') and args.save_initial_observation:
        state.world.initiate_observation_cameras()
        state.save_default_observation(output_path=join(agent.llamp_api.obs_dir, 'observation_0.png'))

    """ before planning """
    if args.preview_scene and args.viewer:
        set_renderer(True)
        wait_unlocked()

    """ solving the problem """
    if not args.scene_only:
        agents = [agent]
        processes = exogenous + agents
        evolve_kwargs = dict(processes=processes, once=not args.monitoring, verbose=False)

        if args.record_mp4:
            mp4_path = join(agent.exp_dir, f"{agent.timestamped_name}.mp4")
            with VideoSaver(mp4_path):
                evolve_processes(state, **evolve_kwargs)
            myprint(f'\n\nsaved mp4 to {mp4_path}\n\n')
        else:
            max_time = 8 * 60
            with timeout(duration=max_time):
                evolve_processes(state, **evolve_kwargs)

        ## failed
        if agent.plan_len == 0:
            if not SAVE_COLLISIONS:
                myprint('failed to find any plans')
                disconnect()
                return

    output_dir = agent.exp_dir
    if record_problem and not isinstance(goals, tuple):
        state.restore()  ## go back to initial state
        state.world.save_test_case(output_dir, goal=goals, init=init, domain=domain, stream=stream,
                                   pddlstream_kwargs=solver_kwargs, problem=problem)

        ## putting solutions from all methods in the same directory as the problem
        if comparing:
            reorg_output_dirs(args.exp_name, output_dir, log_failures=solver_kwargs['log_failures'])
        else:
            print('saved planning data to ' + output_dir)

    if record_plans:
        from world_builder.paths import KITCHEN_WORLD
        KITCHEN_WORLD = abspath(KITCHEN_WORLD.replace('kitchen-worlds', '../kitchen-worlds'))
        dir_name = agent.timestamped_name
        if state.world.note is not None and not args.scene_only:
            dir_name += f'_{state.world.note}'
        data_path = join(KITCHEN_WORLD, 'outputs', problem, dir_name)
        save_to_outputs_folder(output_dir, data_path, data_generation=data_generation,
                               multiple_solutions=args.dataset_mode)
        if SAVE_COLLISIONS:
            file = 'collisions.pkl'
            root_dir = '/home/yang/Documents/cognitive-architectures/bullet/'
            paths = ['pybullet_planning/world_builder/', 'examples/']
            for pp in paths:
                ff = join(root_dir, pp, file)
                if isfile(ff):
                    shutil.move(ff, join(data_path, file))
                    print('moved', ff, 'to', data_path)
                    break
        if solver_kwargs['fc'] is not None:
            solver_kwargs['fc'].dump_log(join(data_path, f'diverse_plans.json'))
        if isdir(data_path) or args.scene_only:
            print('saved data to', data_path)
        else:
            print('failed to find any plans', data_path)

    clear_planning_dir(run_dir=dirname(__file__))

    if reset:
        reset_simulation()
    else:
        disconnect()

    return agent.commands, output_dir
