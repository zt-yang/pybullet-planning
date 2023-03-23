import os
import numpy as np
import trimesh
import h5py

from nsplan_tools.utils.acronym import create_gripper_marker
import nsplan_tools.utils.transformations as tra

def main():
    hand = "/home/weiyu/Research/nsplan/original/kitchen-worlds/assets/models/franka_description/robots/hand_se3.urdf"
    hand = trimesh.load(hand)
    hand.show()


def get_acronym_grasps():

    grasp_dir = "/home/weiyu/data_drive/shapenet/acronym_meshes/grasps"
    mesh_dir = "/home/weiyu/data_drive/shapenet/acronym_meshes"

    num_grasps = 20

    total_count = 0
    visual_count = 0
    for grasp_file in os.listdir(grasp_dir):

        if "Mug" not in grasp_file:
            continue

        print("-" * 20)

        grasp_file = os.path.join(grasp_dir, grasp_file)

        data = h5py.File(grasp_file, "r")
        mesh_fname = data["object/file"][()].decode('utf-8')
        mesh_scale = data["object/scale"][()]

        shapenet_id = mesh_fname.split("/")[-1].split(".")[0]

        obj_mesh = trimesh.load(os.path.join(mesh_dir, mesh_fname))

        print(os.path.join(mesh_dir, mesh_fname))
        print(mesh_scale)

        obj_mesh = obj_mesh.apply_scale(mesh_scale)

        data = h5py.File(grasp_file, "r")
        T = np.array(data["grasps/transforms"])
        success = np.array(data["grasps/qualities/flex/object_in_gripper"])

        # successful_grasps = [
        #     create_gripper_marker(color=[0, 255, 0]).apply_transform(t)
        #     for t in T[np.random.choice(np.where(success == 1)[0], num_grasps)]
        # ]

        grasp = T[np.random.choice(np.where(success == 1)[0], 1)][0]
        print(grasp)

        vis_grasp = create_gripper_marker(color=[0, 255, 0]).apply_transform(grasp)


        table_mesh = trimesh.creation.box([1, 1, 0])

        trimesh.Scene([obj_mesh] + [vis_grasp] + [table_mesh]).show()

        # # find object color mesh in shapenet
        # visual_mesh_file = os.path.join(shapenet_sem_dir, "{}.obj".format(shapenet_id))
        # print(visual_mesh_file)
        #
        # total_count += 1
        #
        # if os.path.exists(visual_mesh_file):
        #     print("visual mesh exist?", os.path.exists(visual_mesh_file))
        #     visual_mesh = trimesh.load(visual_mesh_file)
        #     print(visual_mesh)
        #     # visual_mesh.apply_scale(mesh_scale)
        #
        #     print(visual_mesh.bounds)
        #     # visual_mesh.show()
        #
        #     scale_transformation = np.eye(4)
        #     scale_transformation[:3, :3] *= mesh_scale
        #     print(scale_transformation)
        #     visual_mesh.apply_transform(scale_transformation)
        #
        #     print(mesh_scale)
        #
        #     print(visual_mesh.bounds)
        #     trimesh.Scene([visual_mesh] + [table_mesh] + successful_grasps).show()
        #
        #     visual_count += 1


def get_object_grasp(num_grasps=10):

    model_file = "/home/weiyu/data_drive/structformer_assets/acronym_handpicked_v4_textured_acronym_scale/visual/Bowl_8e840ba109f252534c6955b188e290e0_S.obj"
    grasp_file = "/home/weiyu/data_drive/shapenet/acronym_meshes/grasps/Bowl_8e840ba109f252534c6955b188e290e0_0.020694713428071655.h5"

    data = h5py.File(grasp_file, "r")
    mesh_fname = data["object/file"][()].decode('utf-8')
    mesh_scale = data["object/scale"][()]
    print(mesh_scale)

    T = np.array(data["grasps/transforms"])
    success = np.array(data["grasps/qualities/flex/object_in_gripper"])
    successful_grasps = [t
        for t in T[np.random.choice(np.where(success == 1)[0], num_grasps)]
    ]

    obj_mesh = trimesh.load(model_file)

    for grasp in successful_grasps:
        print(grasp)

        pos = grasp[:3, 3]
        rot = tra.euler_from_matrix(grasp)
        print(pos.tolist() + [*rot])

        vis_grasp = create_gripper_marker(color=[0, 255, 0]).apply_transform(grasp)
        trimesh.Scene([obj_mesh, vis_grasp]).show()




if __name__ == "__main__":
    get_object_grasp()