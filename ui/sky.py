"""A small, camera-centred sky dome for the perspective viewer."""
from math import cos, pi, sin

import numpy as np
from panda3d.core import (Geom, GeomNode, GeomTriangles, GeomVertexData,
                          GeomVertexFormat, GeomVertexWriter, Texture)

from .volumetric_clouds import VolumetricClouds


def _noise(width, height, cells_x, cells_y, rng):
    """Smooth, horizontally periodic value noise for a seamless sky."""
    grid = rng.random((cells_y + 1, cells_x))
    x = np.arange(width) * cells_x / width
    y = np.linspace(0, cells_y, height, endpoint=False)
    x0 = x.astype(int)
    y0 = y.astype(int)
    dx = x - x0
    dy = y - y0
    dx = dx * dx * (3 - 2 * dx)
    dy = dy * dy * (3 - 2 * dy)
    x1 = (x0 + 1) % cells_x
    bottom = grid[y0[:, None], x0] * (1 - dx) + grid[y0[:, None], x1] * dx
    top = grid[(y0 + 1)[:, None], x0] * (1 - dx) + grid[(y0 + 1)[:, None], x1] * dx
    return bottom * (1 - dy[:, None]) + top * dy[:, None]


def _sky_texture():
    """Bake the gradient and cloud shapes once; no sky work runs per frame."""
    width, height = 2048, 512
    scale = width / 1024
    rng = np.random.default_rng(163)
    elevation = np.linspace(0, 1, height, endpoint=False)[:, None]
    horizon = np.array([.61, .80, .95])
    zenith = np.array([.18, .45, .79])
    gradient = np.clip(elevation * 1.5, 0, 1) ** .65
    sky = horizon + gradient[..., None] * (zenith - horizon)

    # Layer small overlapping lobes into distinct cumulus banks. The texture
    # wraps horizontally, so clouds crossing north have no visible seam.
    field = np.full((height, width), -10.0)

    def lobe(cx, cy, rx, ry):
        xs = np.arange(int(cx - rx * 1.3), int(cx + rx * 1.3) + 1)
        ys = np.arange(max(0, int(cy - ry * 1.3)), min(height, int(cy + ry * 1.3) + 1))
        shape = 1 - ((xs[None, :] - cx) / rx) ** 2 - ((ys[:, None] - cy) / ry) ** 2
        index = np.ix_(ys, xs % width)
        field[index] = np.maximum(field[index], shape)

    for i in range(34):
        if i < 20:
            cx = (i + rng.uniform(-.3, .3)) * width / 20
            base = rng.uniform(0, 7) * scale
            w, h = rng.uniform(24, 50) * scale, rng.uniform(9, 16) * scale
        else:
            cx = rng.uniform(0, width)
            base = rng.uniform(22, 80) * scale
            w, h = rng.uniform(30, 80) * scale, rng.uniform(8, 18) * scale
        lobe(cx, base + h * .25, w * .50, h * .28)
        for _ in range(7):
            lobe(cx + rng.uniform(-.38, .38) * w,
                 base + rng.uniform(.30, .65) * h,
                 rng.uniform(.12, .24) * w, rng.uniform(.25, .48) * h)

    detail = (.65 * _noise(width, height, 96, 24, rng)
              + .35 * _noise(width, height, 192, 48, rng))
    cover = np.clip((field + (detail - .5) * .20 + .08) / .23, 0, 1)
    cover = cover * cover * (3 - 2 * cover)
    cover *= np.clip(elevation / .025, 0, 1) * np.clip((1 - elevation) / .18, 0, 1)
    cloud = np.array([.87, .91, .95]) + detail[..., None] * np.array([.12, .08, .04])
    pixels = sky * (1 - cover[..., None] * .92) + cloud * cover[..., None] * .92
    pixels = np.asarray(np.clip(pixels * 255, 0, 255), dtype=np.uint8)

    texture = Texture('daytime-sky')
    texture.setup2dTexture(width, height, Texture.T_unsigned_byte, Texture.F_rgb8)
    texture.setRamImageAs(pixels.tobytes(), 'RGB')
    texture.setWrapU(Texture.WM_repeat)
    texture.setWrapV(Texture.WM_clamp)
    texture.setMinfilter(Texture.FT_linear_mipmap_linear)
    texture.setMagfilter(Texture.FT_linear)
    return texture


class SkyDome:
    def __init__(self, render, volumetric_clouds=False):
        segments, rings, radius = 64, 16, 5000
        data = GeomVertexData('sky', GeomVertexFormat.getV3t2(), Geom.UH_static)
        vertices, uv = GeomVertexWriter(data, 'vertex'), GeomVertexWriter(data, 'texcoord')
        for ring in range(rings + 1):
            elevation = pi * ring / (2 * rings)
            for segment in range(segments + 1):
                azimuth = 2 * pi * segment / segments
                vertices.addData3(radius * cos(elevation) * cos(azimuth),
                                  radius * cos(elevation) * sin(azimuth),
                                  radius * sin(elevation))
                uv.addData2(segment / segments, ring / rings)
        triangles = GeomTriangles(Geom.UH_static)
        for ring in range(rings):
            for segment in range(segments):
                a = ring * (segments + 1) + segment
                b = a + segments + 1
                triangles.addVertices(a, b, a + 1)
                triangles.addVertices(a + 1, b, b + 1)
        geom = Geom(data)
        geom.addPrimitive(triangles)
        node = GeomNode('sky-dome')
        node.addGeom(geom)
        self.root = render.attachNewNode(node)
        self.root.setTexture(_sky_texture())
        self.root.setTwoSided(True)
        self.root.setLightOff()
        self.root.setDepthTest(False)
        self.root.setDepthWrite(False)
        self.root.setBin('background', 0)
        self.clouds = VolumetricClouds(self.root) if volumetric_clouds else None

    def update(self, camera_position, perspective):
        if perspective:
            self.root.setPos(camera_position)
            self.root.show()
        else:
            self.root.hide()
            if self.clouds is not None:
                self.clouds.deactivate()

    def close(self, base):
        if self.clouds is not None:
            self.clouds.close(base)
        self.root.removeNode()
