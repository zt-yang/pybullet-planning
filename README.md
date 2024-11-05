# Long-Horizon Manipulation Planning Toolbox

This toolbox helps you solve long-horizon mobile manipulation problems using planning or policies. 

It includes utility functions for
* procedurally generating scenes from `.urdf`, `.sdf`, `.obj`, and other mesh files.
  * output in `.lisdf` format that's an extension of `.sdf` format that supports including `.urdf` files and camera poses
  * support loading scenes in pybullet or in web front
* solving long-horizon problems using a task and motion planner `pddlstream`, including
  * samplers used by the planner for mobile manipulation and NAMO domains 
  * tools for speeding up planning based on
    * plan feasibility prediction ([PIGINet](https://piginet.github.io/) project)
    * vlm subgoal/action planning ([VLM-TAMP](https://zt-yang.github.io/vlm-tamp-robot) project)
    * state-space reduction (e.g., heuristic object reduction; identify frequently collided objects during planning)
    * action-space reduction (e.g., remove operators, axioms from pddl file; save databases of grasp, pose, configuration)
    * HPN-based (hierarchical planning in the now) hierarchical planning
  * scripts for generating images, animation, and videos from generated trajectories in pybullet and isaac gym 

We recommend that you use the [kitchen-world](https://github.com/Learning-and-Intelligent-Systems/kitchen-worlds/tree/main) repo, which includes this toolbox, if
* you are interested in procedural generation of kitchen scenes, because various assets and example layouts are provided there.
* you are interested in generating trajectories using motion planning or task and motion planning.

## Installation

The following is included in the kitchen-world installation guide if you took that route.

1. Clone and grab the submodules, may take a while

```shell
git clone --recurse-submodules git@github.com:zt-yang/pybullet_planning.git
cd pybullet_planning
```

2. Install dependencies

```shell
conda create -n pybullet python==3.8
pip install -r requirements.txt
conda activate pybullet
```

3. Build IK solvers

IKFast solver for PR2 arm planning (see [troubleshooting notes](pybullet_tools/ikfast/troubleshooting.md) if encountered error):

```shell
## sudo apt-get install python-dev
(cd pybullet_tools/ikfast/pr2; python setup.py)
```

If using Ubuntu, install TracIK for PR2 base, torso, and arm planning:

```shell
sudo apt-get install libeigen3-dev liborocos-kdl-dev libkdl-parser-dev liburdfdom-dev libnlopt-dev libnlopt-cxx-dev swig
pip install git+https://github.com/mjd3/tracikpy.git
```

Attempting to install tracikpy on MacOS:

```shell
brew install eigen orocos-kdl nlopt urdfdom
```

### Issue: `C++`

```shell
 xcrun: error: invalid active developer path (/Library/Developer/CommandLineTools), missing xcrun at: /Library/Developer/CommandLineTools/usr/bin/xcrun
```
solution, takes a while to install
```shell
xcode-select --install
```

## Issue: Eigen path not found

```shell
/usr/local/include/kdl/jacobian.hpp:26:10: fatal error: 'Eigen/Core' file not found
```

---
<!---
## Overview

Initially developed by Caelan for solving PDDLStream planning problems:
* `pybullet_tools`: basic Util functions for interfacing with pybullet and stream functions
* `databases`: saved grasps and other samples for faster debugging
* `images`: for visualization

Added by Yang for procedurally generating scenes and problems, solving partially-observable problems, and processing the data generated by planners for learning applications.
* `cogarch_tools`: for agents and processes planning and interacting with the world continuously 

---

## Tutorials - Procedural Scene Generation

The `/world_builder` directory includes functions for
* Building a `World` object, adding entities such as `Robot`, `Movable`, `Joint`, `Surface`, `Space`. For example, as shown in scripts `tutorials/test_assets.py`

```python
world = 
```
* Movable and articulated objects are usually sampled from assets of object categories, then randomly located in collision-free poses given supporting regions
* Procedurally generate scenes based on 
  * an `.svg` file that roughly lay out furniture types, locations; movable types and supporting regions
  * a function that 
* Initiating a scene from an `.svg` file that roughly lay out object types and locations

Run a flying panda gripper (feg) in kitchen simulation:
```shell
python tutorials/test_floating_gripper.py -t test_feg_pick
python tutorials/test_data_generation.py -c kitchen_full_feg.yaml
```

---

-->

## Trouble-Shooting 

See [trouble-shooting.md](trouble-shooting.md)

## Acknowledgements

* Developed based on Caelan Garrett's [pybullet_planning](https://github.com/caelan/pybullet-planning) utility functions for robotic motion planning, manipulation planning, and task and motion planning (TAMP).
* The development is partially performed during internship at NVIDIA Research, Seattle Robotics Lab.