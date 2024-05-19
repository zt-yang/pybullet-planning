# Toolbox: pybullet_planning

A fork of Caelan Garrett's [pybullet_planning](https://github.com/caelan/pybullet-planning) utility functions for robotic motion planning, manipulation planning, and task and motion planning (TAMP).

## Setup

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

TracIK for PR2 base, torso, and arm planning:

```shell
sudo apt-get install libeigen3-dev liborocos-kdl-dev libkdl-parser-dev liburdfdom-dev libnlopt-dev libnlopt-cxx-dev swig
pip install git+https://github.com/mjd3/tracikpy.git
```

---

## Overview

Initially developed by Caelan for solving fully-observable PDDLStream planning problems:
* `pybullet_tools`: basic Util functions for interfacing with pybullet and stream functions
* `databases`: saved grasps for robots
* `images`: for visualization

Added by Yang for procedurally generating scenes and problems, solving partially-observable problems, and processing the data generated by planners for learning applications.
* `cogarch_tools`: for agents and processes planning and interacting with the world continuously 

---

## Tutorials (to be updated)

Run a flying panda gripper (feg) in kitchen simulation:
```shell
python tutorials/test_floating_gripper.py -t test_feg_pick
python tutorials/test_data_generation.py -c kitchen_full_feg.yaml
```

## Issues:

### On MacOS Version with `untangle`

error message:

```shell
  File ".../Documents/simulators/vlm-tamp/pybullet_planning/world_builder/world_utils.py", line 157, in read_xml
    content = untangle.parse(plan_path).svg.g.g.g
  File ".../miniconda3/envs/cogarch/lib/python3.8/site-packages/untangle.py", line 205, in parse
    parser.parse(filename)
  File ".../miniconda3/envs/cogarch/lib/python3.8/xml/sax/expatreader.py", line 111, in parse
    xmlreader.IncrementalParser.parse(self, source)
  File ".../miniconda3/envs/cogarch/lib/python3.8/xml/sax/xmlreader.py", line 125, in parse
    self.feed(buffer)
  File ".../miniconda3/envs/cogarch/lib/python3.8/xml/sax/expatreader.py", line 217, in feed
    self._parser.Parse(data, isFinal)
  File "/private/var/folders/nz/j6p8yfhx1mv_0grj5xl4650h0000gp/T/abs_40bvsc0ovr/croot/python-split_1710966196798/work/Modules/pyexpat.c", line 668, in ExternalEntityRef

loading floor plan kitchen_v2.svg...
  File ".../miniconda3/envs/cogarch/lib/python3.8/site-packages/defusedxml/expatreader.py", line 46, in defused_external_entity_ref_handler
    raise ExternalReferenceForbidden(context, base, sysid, pubid)
defusedxml.common.ExternalReferenceForbidden: ExternalReferenceForbidden(system_id='http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd', public_id=-//W3C//DTD SVG 1.1//EN)
```

solution:

```shell
pip uninstall untangle
pip install untangle==1.1.1
```