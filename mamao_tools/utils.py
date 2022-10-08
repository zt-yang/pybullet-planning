import json
import shutil
from os.path import join, isdir, abspath, isfile
from os import listdir, getcwd
import copy
import untangle


if 'zhutiany' in getcwd():
    DATASET_PATH = '/home/zhutiany/Documents/mamao-data'
elif 'yang' in getcwd():
    DATASET_PATH = '/home/yang/Documents/fastamp-data'
else: ## not tested
    DATASET_PATH = '../../fastamp-data'


def get_feasibility_checker(run_dir, mode, diverse=False):
    from .feasibility_checkers import PassAll, ShuffleAll, Oracle, PVT
    if mode == 'binary':
        mode = 'pvt'
        diverse = False
    if mode == 'None':
        return PassAll(run_dir)
    elif mode == 'shuffle':
        return ShuffleAll(run_dir)
    elif mode == 'oracle':
        plan = get_successful_plan(run_dir)
        return Oracle(run_dir, plan)
    elif 'pvt-task' in mode:
        task_name = abspath(run_dir).replace(DATASET_PATH, '').split('/')[1]
        return PVT(run_dir, mode=mode, task_name=task_name, scoring=diverse)
    elif mode.startswith('pvt'):
        return PVT(run_dir, mode=mode, scoring=diverse)
    return None


def organize_dataset(task_name):
    out_path = join(DATASET_PATH, task_name)
    names = [eval(l) for l in listdir(out_path) if isdir(join(out_path, l))]
    if len(names) == 0: return
    index = max(names)
    missing = list(set(range(index)) - set(names))
    if len(missing) == 0: return
    missing.sort()
    top = index
    moved = []
    for i in range(len(missing)):
        old_dir = join(out_path, str(top))
        while not isdir(old_dir) or str(top) in missing:
            top -= 1
            old_dir = join(out_path, str(top))
        if top in moved:
            break
        print(f'---- moving {top} to {missing[i]}')
        top -= 1
        shutil.move(old_dir, join(out_path, str(missing[i])))
        moved.append(missing[i])


def get_indices_from_config(run_dir):
    config = json.load(open(join(run_dir, 'planning_config.json'), 'r'))
    if 'body_to_name' in config:
        return {k: v for k, v in config['body_to_name'].items()} ## .replace('::', '%')
    return False



def process_value(vv, training=True):
    from pybullet_tools.utils import quat_from_euler
    vv = list(vv)
    ## convert quaternion to euler angles
    if len(vv) == 6:
        quat = quat_from_euler(vv[3:])
        vv = vv[:3] + list(quat)
    return vv


def get_variables_from_pddl_objects(init):
    vs = []
    for i in init:
        vs.extend([a for a in i[1:] if ',' in a])
    return list(set(vs))


def get_variables_from_pddl(facts, objs):
    new_objs = copy.deepcopy(objs) + ['left', 'right']
    new_objs.sort(key=len, reverse=True)
    vs = []
    for f in facts:
        f = f.replace('\n', '').replace('\t', '').strip()[1:-1]
        if ' ' not in f or f.startswith(';'):
            continue
        f = f[f.index(' ')+1:]
        for o in new_objs:
            f = f.replace(o, '')
        f = f.strip()
        if len(f) == 0:
            continue

        if f not in vs:
            found = False
            for v in vs:
                if v in f:
                    found = True
            if not found and 'wconf' not in f:
                vs.append(f)
    return vs


def get_variables(init, objs=None):
    if isinstance(init[0], str):
        vs = get_variables_from_pddl(init, objs)
    else:
        vs = get_variables_from_pddl_objects(init)

    return vs, {vs[i]: f'idx={i}' for i in range(len(vs))}


def get_successful_plan(run_dir, indices={}, continuous={}):
    plan = []
    with open(join(run_dir, 'plan.json'), 'r') as f:
        data = json.load(f)[0]
        actions = data['plan']
        if actions == 'FAILED':
            return None
        vs, inv_vs = get_variables(data['init'])
        for a in actions:
            name = a[a.index("name='")+6: a.index("', args=(")]
            # if 'grasp_handle' in name:
            #     continue
            args = a[a.index("args=(")+6:-2].replace("'", "")
            new_args = parse_pddl_str(args, vs=vs, inv_vs=inv_vs, indices=indices)
            plan.append([name] + new_args)
    return plan


def parse_pddl_str(args, vs, inv_vs, indices={}):
    """ parse a string of string, int, and tuples into a list """

    ## replace those tuples with placeholders that doesn't have ', ' or ' '
    for string, sub in inv_vs.items():
        if string in args:
            args = args.replace(string, sub)

    if ',' in args:
        """  from plan.json
        e.g. 'left', 7, p1=(3.255, 4.531, 0.762, 0.0, -0.0, 2.758), g208=(0, 0.0, 0.304, -3.142, 0, 0),
             q624=(3.959, 4.687, 0.123, -1.902), c528=t(7, 60), wconf64 """
        args = args.split(', ')

    else:
        """  from problem.pddl
        e.g. pose veggiecauliflower p0=(3.363, 2.794, 0.859, 0.0, -0.0, 1.976) """
        args = args.split(' ')

    ## replace those placeholders with original values
    new_args = []
    for arg in args:
        if arg in indices:
            new_args.append(indices[arg])
        elif 'idx=' in arg:
            idx = int(eval(arg.replace('idx=', '')))
            new_args.append(vs[idx])
        else:
            new_args.append(arg)
    return new_args


def get_plan(run_dir, indices={}, continuous={}, plan_json=None):
    if indices == {}:
        indices = get_indices_from_config(run_dir)
    if plan_json is not None:
        plan = json.load(open(plan_json, 'r'))['plan']
    else:
        plan = get_successful_plan(run_dir, indices)

    ## add the continuous mentioned in plan
    new_continuous = {}
    for a in plan:
        for arg in a[1:]:
            if '=' in arg:
                name, value = arg.split('=')
                value = value.replace('t(', '(')
                if name not in continuous and name not in new_continuous:
                    v = list(eval(value)) if ('(' in value) else [eval(value)]
                    if len(v) != 2:  ## sampled trajectory
                        new_continuous[name] = process_value(v)
    return plan, new_continuous
