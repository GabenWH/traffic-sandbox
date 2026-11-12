"""An optional low-resolution cloud pass for the Panda3D perspective sky."""
import logging

import numpy as np
from panda3d.core import (CardMaker, ClockObject, FrameBufferProperties, NodePath,
                          OrthographicLens, Point2, Point3, Shader, Texture, Vec2)


_QUAD_VERTEX = """#version 330
in vec4 p3d_Vertex;
in vec2 p3d_MultiTexCoord0;
out vec2 uv;

void main() {
    gl_Position = vec4(p3d_Vertex.xz, 0.0, 1.0);
    uv = p3d_MultiTexCoord0;
}
"""

_CLOUD_FRAGMENT = """#version 330
uniform sampler3D density_noise;
uniform sampler2D weather_map;
uniform vec3 eye;
uniform vec3 lower_left;
uniform vec3 right_span;
uniform vec3 up_span;
uniform float cloud_time;
in vec2 uv;
out vec4 cloud;

const float cloud_base = 2200.0;
const float cloud_top = 5000.0;
const float max_distance = 64000.0;
const int steps = 36;
const vec3 sun = vec3(-0.48, -0.32, 0.817);

float density(vec3 position) {
    float height = (position.z - cloud_base) / (cloud_top - cloud_base);
    float profile = smoothstep(0.0, 0.22, height) * (1.0 - smoothstep(0.55, 1.0, height));
    if (profile <= 0.0) return 0.0;
    vec2 weather_position = position.xy - vec2(27.0, 12.0) * cloud_time;
    float coverage = texture(weather_map, weather_position / 56000.0).r;
    if (coverage < 0.40) return 0.0;
    vec3 noise_position = vec3(weather_position, position.z) / vec3(15500.0, 15500.0, 7000.0);
    float shape = texture(density_noise, noise_position).r;
    float threshold = 0.51 + 0.23 * (1.0 - profile) + (0.58 - coverage) * 0.85;
    return clamp((shape - threshold) * 5.0, 0.0, 1.0) * profile;
}

void main() {
    cloud = vec4(0.0);
    vec3 ray = normalize(lower_left + uv.x * right_span + uv.y * up_span);
    if (ray.z <= 0.0) return;

    float start = max(0.0, (cloud_base - eye.z) / ray.z);
    float end = min(max_distance, (cloud_top - eye.z) / ray.z);
    if (end <= start) return;

    float step_length = (end - start) / float(steps);
    // Offset samples per pixel to break up bands on long, shallow rays.
    float jitter = fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
    float sample_offset = mix(0.15, 0.85, jitter);
    float transmittance = 1.0;
    for (int i = 0; i < steps; ++i) {
        float distance = start + (float(i) + sample_offset) * step_length;
        vec3 position = eye + ray * distance;
        float amount = density(position);
        if (amount <= 0.0) continue;

        float sunlight = exp(-1.4 * density(position + sun * 520.0));
        float height_light = smoothstep(cloud_base, cloud_top, position.z);
        vec3 color = mix(vec3(0.50, 0.58, 0.70), vec3(1.0, 0.98, 0.94),
                         clamp(0.72 * sunlight + 0.28 * height_light, 0.0, 1.0));
        float fade = 1.0 - smoothstep(36000.0, max_distance, distance);
        float opacity = 1.0 - exp(-amount * fade * step_length * 0.0025);
        cloud.rgb += transmittance * opacity * color;
        transmittance *= 1.0 - opacity;
        if (transmittance < 0.015) break;
    }
    cloud.a = 1.0 - transmittance;
}
"""

_SKY_VERTEX = """#version 330
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
out vec3 sky_direction;

void main() {
    sky_direction = p3d_Vertex.xyz;
    gl_Position = p3d_ModelViewProjectionMatrix * p3d_Vertex;
}
"""

_SKY_FRAGMENT = """#version 330
uniform sampler2D cloud_texture;
uniform vec2 viewport_size;
uniform vec2 cloud_size;
in vec3 sky_direction;
out vec4 pixel;

void main() {
    float elevation = asin(clamp(normalize(sky_direction).z, 0.0, 1.0));
    float gradient = pow(clamp(elevation * 0.95493, 0.0, 1.0), 0.65);
    vec3 sky = mix(vec3(0.61, 0.80, 0.95), vec3(0.18, 0.45, 0.79), gradient);
    // Panda can pad the texture to a power of two. Sample only the region
    // the offscreen camera rendered, including at the edge when upscaling.
    vec2 texel = clamp(gl_FragCoord.xy / viewport_size * cloud_size, vec2(0.5), cloud_size - 0.5);
    vec4 cloud = texture(cloud_texture, texel / vec2(textureSize(cloud_texture, 0)));
    pixel = vec4(sky * (1.0 - cloud.a) + cloud.rgb, 1.0);
}
"""


def _noise_texture(name, size, dimensions, octaves, seed):
    """Bake tileable value noise with a few scales into an 8-bit texture."""
    rng = np.random.default_rng(seed)
    noise = np.zeros((size,) * dimensions, dtype=np.float32)
    for cells, weight in octaves:
        grid = rng.random((cells,) * dimensions, dtype=np.float32)
        coordinates = np.arange(size, dtype=np.float32) * (cells / size)
        low = coordinates.astype(int)
        high = (low + 1) % cells
        fraction = coordinates - low
        blend = (fraction * fraction * (3 - 2 * fraction)).astype(np.float32)
        for axis in range(dimensions):
            shape = [1] * dimensions
            shape[axis] = size
            amount = blend.reshape(shape)
            grid = np.take(grid, low, axis=axis) * (1 - amount) + np.take(grid, high, axis=axis) * amount
        noise += weight * grid

    texture = Texture(name)
    if dimensions == 3:
        texture.setup3dTexture(size, size, size, Texture.T_unsigned_byte, Texture.F_red)
        texture.setWrapW(Texture.WM_repeat)
    else:
        texture.setup2dTexture(size, size, Texture.T_unsigned_byte, Texture.F_red)
    texture.setRamImage(np.rint(noise * 255).astype(np.uint8).tobytes())
    texture.setWrapU(Texture.WM_repeat)
    texture.setWrapV(Texture.WM_repeat)
    texture.setMinfilter(Texture.FT_linear)
    texture.setMagfilter(Texture.FT_linear)
    return texture


class VolumetricClouds:
    def __init__(self, dome):
        self.dome = dome
        self.scene = NodePath('cloud-pass')
        self.buffer = None
        self.camera = None
        self.quad = None
        self.rays = None
        self.output_size = None
        self.available = True

    def set_view(self, camera, render, lens):
        transform = camera.getMat(render)
        rays = []
        for x, y in ((-1, -1), (1, -1), (-1, 1)):
            near, far = Point3(), Point3()
            lens.extrude(Point2(x, y), near, far)
            rays.append(transform.xformVec(near))
        lower_left, lower_right, upper_left = rays
        right_span = lower_right - lower_left
        up_span = upper_left - lower_left
        upper_right = upper_left + right_span
        if max(ray.z for ray in (*rays, upper_right)) <= 0:
            self.deactivate()
            return
        self.rays = camera.getPos(render), lower_left, right_span, up_span

    def deactivate(self):
        self.rays = None
        if self.buffer is not None:
            self.buffer.setActive(False)

    def _build_quad(self):
        card = CardMaker('cloud-march')
        card.setFrameFullscreenQuad()
        self.quad = self.scene.attachNewNode(card.generate())
        self.quad.setY(1)
        self.quad.setDepthTest(False)
        self.quad.setDepthWrite(False)
        self.cloud_shader = Shader.make(Shader.SL_GLSL, _QUAD_VERTEX, _CLOUD_FRAGMENT)
        self.sky_shader = Shader.make(Shader.SL_GLSL, _SKY_VERTEX, _SKY_FRAGMENT)
        self.quad.setShader(self.cloud_shader)
        self.quad.setShaderInput('density_noise', _noise_texture(
            'cloud-density', 64, 3, ((4, .54), (8, .25), (16, .14), (32, .07)), 32))
        self.quad.setShaderInput('weather_map', _noise_texture(
            'cloud-coverage', 128, 2, ((5, .72), (10, .20), (20, .08)), 53))

    def _open_buffer(self, base, width, height):
        self._close_buffer(base)
        framebuffer = FrameBufferProperties()
        framebuffer.setRgbaBits(8, 8, 8, 8)
        texture = Texture('cloud-composite')
        texture.setWrapU(Texture.WM_clamp)
        texture.setWrapV(Texture.WM_clamp)
        texture.setMinfilter(Texture.FT_linear)
        texture.setMagfilter(Texture.FT_linear)
        buffer = base.win.makeTextureBuffer('clouds', (width + 1) // 2, (height + 1) // 2,
                                            texture, False, framebuffer)
        if buffer is None:
            self._fallback('could not allocate a cloud buffer')
            return
        self.buffer = buffer
        buffer.setClearColor((0, 0, 0, 0))
        buffer.setClearColorActive(True)
        lens = OrthographicLens()
        lens.setFilmSize(2, 2)
        lens.setNearFar(0.01, 10)
        self.camera = base.makeCamera(buffer, scene=self.scene, lens=lens, camName='cloud-camera')
        self.camera.reparentTo(self.scene)
        self.output_size = (width, height)
        self.dome.setShader(self.sky_shader)
        self.dome.setShaderInput('cloud_texture', buffer.getTexture())
        self.dome.setShaderInput('viewport_size', Vec2(width, height))
        self.dome.setShaderInput('cloud_size', Vec2(buffer.getXSize(), buffer.getYSize()))

    def prepare(self, base):
        if self.rays is None or not self.available:
            return
        win = base.win
        if win is None or not win.isValid():
            return
        size = (win.getXSize(), win.getYSize())
        if min(size) < 2:
            return
        if self.quad is None:
            if not win.getGsg().getSupports3dTexture():
                self._fallback('3D textures are unavailable')
                return
            self._build_quad()
        if self.cloud_shader.getErrorFlag() or self.sky_shader.getErrorFlag():
            self._close_buffer(base)
            self._fallback('a cloud shader failed to compile')
            return
        if self.output_size != size:
            self._open_buffer(base, *size)
        if self.buffer is None:
            return
        for name, value in zip(('eye', 'lower_left', 'right_span', 'up_span'), self.rays):
            self.quad.setShaderInput(name, value)
        self.quad.setShaderInput('cloud_time', ClockObject.getGlobalClock().getFrameTime())
        self.buffer.setActive(True)

    def _fallback(self, reason):
        self.available = False
        logging.getLogger(__name__).warning('Using the baked sky because %s.', reason)

    def _close_buffer(self, base):
        if self.buffer is None:
            return
        self.dome.clearShader()
        self.dome.clearShaderInput('cloud_texture')
        self.dome.clearShaderInput('viewport_size')
        self.dome.clearShaderInput('cloud_size')
        if self.camera in base.camList:
            base.camList.remove(self.camera)
        self.camera.removeNode()
        base.graphicsEngine.removeWindow(self.buffer)
        self.buffer = None
        self.camera = None
        self.output_size = None

    def close(self, base):
        self._close_buffer(base)
        self.scene.removeNode()
