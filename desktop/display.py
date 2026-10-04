"""Use one display stretch for before/after comparison and the exported PNG."""
import numpy as np


def stretch_ranges(rgb):
    ranges = []
    for i in range(3):
        values = rgb[:, :, i]
        values = values[np.isfinite(values)]
        low, high = np.percentile(values, [2, 98]) if values.size else (0, 1)
        ranges.append([float(low), float(high if high > low else low + 1)])
    return ranges


def preview_rgb(rgb, ranges):
    image = np.zeros(rgb.shape, dtype='uint8')
    for i, (low, high) in enumerate(ranges):
        image[:, :, i] = np.nan_to_num(np.clip((rgb[:, :, i] - low) / (high - low), 0, 1) * 255).astype('uint8')
    image[~np.isfinite(rgb).all(axis=2)] = 0
    return image
