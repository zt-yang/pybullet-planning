import PIL.Image
import numpy as np
from tqdm import tqdm
import time
from os.path import join, isdir, abspath, dirname, isfile
from pybullet_tools.utils import get_aabb_extent, get_aabb_center, AABB
from pybullet_tools.bullet_utils import get_segmask


def hex_to_rgba(color):
    """
    Turn a string hex color to a (4,) RGBA color.
    Parameters
    -----------
    color: str, hex color
    Returns
    -----------
    rgba: (4,) np.uint8, RGBA color
    """
    value = str(color).lstrip('#').strip()
    if len(value) == 6:
        rgb = [int(value[i:i + 2], 16) for i in (0, 2, 4)]
        rgba = np.append(rgb, 255).astype(np.uint8) / 255
    else:
        raise ValueError('Only RGB supported')

    return rgba


RED = hex_to_rgba('#e74c3c')
ORANGE = hex_to_rgba('#e67e22')
BLUE = hex_to_rgba('#3498db')
GREEN = hex_to_rgba('#2ecc71')
YELLOW = hex_to_rgba('#f1c40f')
PURPLE = hex_to_rgba('#9b59b6')
GREY = hex_to_rgba('#95a5a6')
CLOUD = hex_to_rgba('#ecf0f1')
MIDNIGHT = hex_to_rgba('#34495e')
WHITE = hex_to_rgba('#ffffff')
BLACK = hex_to_rgba('#000000')

DARKER_RED = hex_to_rgba('#c0392b')
DARKER_ORANGE = hex_to_rgba('#d35400')
DARKER_BLUE = hex_to_rgba('#2980b9')
DARKER_GREEN = hex_to_rgba('#27ae60')
DARKER_YELLOW = hex_to_rgba('#f39c12')
DARKER_PURPLE = hex_to_rgba('#8e44ad')
DARKER_GREY = hex_to_rgba('#7f8c8d')
DARKER_MIDNIGHT = hex_to_rgba('#2c3e50')
DARKER_CLOUD = hex_to_rgba('#bdc3c7')

RAINBOW_COLORS = [RED, ORANGE, YELLOW, GREEN, BLUE, PURPLE, MIDNIGHT, GREY]
DARKER_COLORS = [DARKER_RED, DARKER_ORANGE, DARKER_YELLOW, DARKER_GREEN,
                 DARKER_BLUE, DARKER_PURPLE, DARKER_MIDNIGHT, DARKER_GREY]


def draw_bb(im, bb):
    from PIL import ImageOps
    im2 = np.array(ImageOps.grayscale(im))
    for j in range(bb.lower[0], bb.upper[0]+1):
        for i in [bb.lower[1], bb.upper[1]]:
            im2[i, j] = 255
    for i in range(bb.lower[1], bb.upper[1]+1):
        for j in [bb.lower[0], bb.upper[0]]:
            im2[i, j] = 255
    im.show()
    PIL.Image.fromarray(im2).show()


def crop_image(im, bb, width, height, N_PX):
    if bb is None:
        # crop the center of the blank image
        left = int((width - N_PX) / 2)
        top = int((height - N_PX) / 2)
        right = left + N_PX
        bottom = top + N_PX
        cp = (left, top, right, bottom)
        im = im.crop(cp)
        return im

    # draw_bb(im, bb)
    need_resizing = False
    size = N_PX
    padding = 30
    dx, dy = get_aabb_extent(bb)
    cx, cy = get_aabb_center(bb)
    dmax = max(dx, dy)
    if dmax > N_PX:
        dmax += padding * 2
        if dmax > height:
            dmax = height
            cy = height / 2
        need_resizing = True
        size = dmax
    left = max(0, int(cx - size / 2))
    top = max(0, int(cy - size / 2))
    right = left + size
    bottom = top + size
    if right > width:
        right = width
        left = width - size
    if bottom > height:
        bottom = height
        top = height - size
    cp = (left, top, right, bottom)

    im = im.crop(cp)
    if need_resizing:
        im = im.resize((N_PX, N_PX))
    return im


def get_mask_bb(mask):
    if np.all(mask == 0):
        return None
    col = np.max(mask, axis=0)  ## 1280
    row = np.max(mask, axis=1)  ## 960
    col = np.where(col == 1)[0]
    row = np.where(row == 1)[0]
    return AABB(lower=(col[0], row[0]), upper=(col[-1], row[-1]))


def expand_mask(mask):
    y = np.expand_dims(mask, axis=2)
    return np.concatenate((y, y, y), axis=2)


def make_image_background(old_arr):
    new_arr = np.ones_like(old_arr)
    new_arr[:, :, 0] = 178
    new_arr[:, :, 1] = 178
    new_arr[:, :, 2] = 204
    return new_arr


##############################################################################


def save_seg_mask(imgs, obj_keys, verbose=False):
    rgb = imgs.rgbPixels[:, :, :3]
    seg = imgs.segmentationMaskBuffer
    unique = get_segmask(seg)
    mask = np.zeros_like(rgb[:, :, 0])
    for k in obj_keys:
        if k in unique:
            c, r = zip(*unique[k])
            mask[(np.asarray(c), np.asarray(r))] = 1
    h, w, _ = rgb.shape
    sum1 = mask.sum()
    sum2 = h * w
    if verbose:
        print(f'\t{round(sum1 / sum2 * 100, 2)}%\t | masked {sum1} out of {sum2} pixels ')
    return (rgb, mask)


def make_composed_image(seg_masks, background, is_movable=False, verbose=False):
    """ input is a list of (rgb, mask) pairs """
    composed_rgb = np.zeros_like(background).astype(np.float64)
    composed_mask = np.zeros_like(seg_masks[0][1])
    for _, seg_mask in seg_masks:
        composed_mask = np.logical_or(composed_mask, seg_mask)
    composed_mask = composed_mask.astype(np.float64)

    composed_mask = expand_mask(composed_mask)
    composed_rgb += np.copy(background) * (1 - composed_mask)

    n = len(seg_masks)
    weights = np.arange(n/2, 3*n/2) / (n*(n+1)/2 + n*n/2)
    weights_second_last = weights[-2]
    weights[1:-1] = weights[:-2]
    weights[0] = weights_second_last
    if verbose:
        print(np.round(weights, decimals=3))
    foregrounds = np.zeros_like(background).astype(np.float64)
    for i, (rgb, mask) in enumerate(seg_masks):
        if is_movable:
            mask_here = expand_mask(mask)
            masked_region = np.copy(rgb) * weights[i] + np.copy(background) * (1 - weights[i])
            foregrounds = mask_here * masked_region + (1 - mask_here) * foregrounds
        else:
            composed_rgb += np.copy(rgb) * composed_mask * weights[i]
    if is_movable:
        composed_rgb += composed_mask * foregrounds

    return composed_rgb


def make_composed_image_multiple_episodes(episodes, image_name, verbose=False, crop=None, **kwargs):
    """ finally crop the image and save it """
    background = episodes[0][0][0][0]
    for seg_masks, is_movable in episodes:
        background = make_composed_image(seg_masks, background, is_movable=is_movable, **kwargs)

    composed_rgb = background.astype(np.uint8)

    h, w, _ = composed_rgb.shape
    im = PIL.Image.fromarray(composed_rgb)
    if crop is not None:
        im = im.crop(crop)

    im.save(image_name)
    if verbose:
        print(f'saved composed image {image_name} from {len(episodes)} episodes')


#################################################################################


def images_to_gif(img_dir, gif_name, filenames, crop=None):
    import imageio
    start = time.time()
    gif_file = join(img_dir, '..', gif_name)
    # print(f'saving to {abspath(gif_file)} with {len(filenames)} frames')
    with imageio.get_writer(gif_file, mode='I') as writer:
        for filename in filenames:
            # image = imageio.imread(filename)
            if crop is not None:
                left, top, right, bottom = crop
                filename = filename[top:bottom, left:right]
            writer.append_data(filename)

    print(f'saved to {abspath(gif_file)} with {len(filenames)} frames in {round(time.time() - start, 2)} seconds')
    return gif_file


def images_to_mp4(images=[], img_dir='images', mp4_name='video.mp4'):
    import cv2
    import os

    fps = 20
    if isinstance(images[0], str):
        images = [img for img in os.listdir(img_dir) if img.endswith(".png")]
        frame = cv2.imread(os.path.join(img_dir, images[0]))
    else:
        frame = images[0]
    height, width, layers = frame.shape

    fourcc = cv2.VideoWriter_fourcc(*'mp4v') ## cv2.VideoWriter_fourcc(*'XVID') ## cv2.VideoWriter_fourcc(*'mp4v')
    video = cv2.VideoWriter(mp4_name, fourcc, fps, (width, height))

    for image in images:
        if isinstance(images[0], str):
            image = cv2.imread(os.path.join(img_dir, image))
        elif isinstance(images[0], np.ndarray) and image.shape[-1] == 4:
            image = image[:, :, :3]
            image = image[...,[2,1,0]].copy() ## RGB to BGR for cv2
        video.write(image)

    cv2.destroyAllWindows()
    video.release()


def make_collage_mp4(mp4s, num_cols, num_rows, size=None, mp4_name='collage.mp4'):
    import cv2
    import numpy as np
    import skvideo.io

    fps = 20
    max_frames = -1
    frames = []
    for mp4 in tqdm(mp4s, desc=f'reading videos'):
        videodata = skvideo.io.vread(mp4)
        frames.append(videodata)  ## np.swapaxes(videodata, 1, 2)
        num_frames, h, w, c = videodata.shape

        if num_frames > max_frames:
            max_frames = num_frames

    if size is None:
        size = (h, w)
        clip_size = (h // num_rows, w // num_cols)
    else:
        clip_size = (size[0] // num_rows, size[1] // num_cols)
    size = size[::-1]
    clip_size = clip_size[::-1]
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  ## cv2.VideoWriter_fourcc(*'XVID') ## cv2.VideoWriter_fourcc(*'mp4v')
    video = cv2.VideoWriter(mp4_name, fourcc, fps, size)

    for i in tqdm(range(max_frames), desc=f'generating collage of {len(mp4s)} videos'):
        rows = []
        this_row = []
        for j, videodata in enumerate(frames):
            img = videodata[i] if i < videodata.shape[0] else videodata[-1]
            img = cv2.resize(img, clip_size)
            img = img[..., [2, 1, 0]].copy()  ## RGB to BGR for cv2
            col = j % num_cols
            this_row.append(img)
            if col == num_cols - 1:
                rows.append(np.hstack(this_row))
                this_row = []
        frame = np.vstack(rows)
        video.write(frame)

    cv2.destroyAllWindows()
    video.release()


def test_make_collage_mp4():
    mp4_dir = '/home/yang/Documents/jupyter-worlds/tests/gym_images/'
    num_cols = 2
    num_rows = 2
    mp4 = join(mp4_dir, 'gym_replay_batch_gym_0101_16:57.mp4')
    mp4s = [mp4] * (num_cols * num_rows)
    make_collage_mp4(mp4s, num_cols, num_rows, mp4_name=join(mp4_dir, 'collage_4by4.mp4'))


if __name__ == "__main__":
    test_make_collage_mp4()