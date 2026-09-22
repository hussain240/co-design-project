"""
This file contains definitions for a simple raytracer.
Copyright Callum and Tony Garnock-Jones, 2008.

This file may be freely redistributed under the MIT license,
http://www.opensource.org/licenses/mit-license.php

From http://www.lshift.net/blog/2008/10/29/toy-raytracer-in-python

-------------------------------------------------------------------------------
OPTIMIZED version (HWSW co-design project). Same scene, same image size, same
algorithm and BIT-IDENTICAL output image (verify_raytrace.py compares the
rendered bytes). Every floating-point expression keeps the original operand
order, so the IEEE-754 results are exactly the same.

  O1  __slots__ on the small hot classes (Vector, Point, Ray).
      Attribute access becomes a slot descriptor (fixed offset in the object)
      instead of a per-instance __dict__ lookup, and object creation no longer
      allocates a dict. Millions of Vector/Point/Ray objects are created.

  O2  Remove run-time "type assertion" calls from the hot path.
      mustBeVector()/mustBePoint()/isPoint() are Python method calls that do
      nothing for valid input; in CPython 3.10 each costs a full frame
      push/pop. The scene only ever passes valid types.

  O3  Loop-invariant code motion in the shadow test (_lightIsVisible).
      The original builds a new, identical Ray(p, l - p) (with a sqrt and a
      normalization) for EVERY object tested; it is now built once per light.

  O4  Inline the hot vector math (intersectionTime, normalization, primary
      ray construction, reflection, closest-hit search) on plain floats,
      avoiding temporary Vector objects and method calls.
-------------------------------------------------------------------------------
"""

import array
import math
from math import sqrt

try:
    import pyperf
except ImportError:          # lets profile_raytrace.py run under python3-dbg
    pyperf = None


DEFAULT_WIDTH = 100
DEFAULT_HEIGHT = 100
EPSILON = 0.00001


class Vector(object):
    __slots__ = ('x', 'y', 'z')                                   # O1

    def __init__(self, initx, inity, initz):
        self.x = initx
        self.y = inity
        self.z = initz

    def __str__(self):
        return '(%s,%s,%s)' % (self.x, self.y, self.z)

    def __repr__(self):
        return 'Vector(%s,%s,%s)' % (self.x, self.y, self.z)

    def magnitude(self):
        x = self.x; y = self.y; z = self.z
        return sqrt((x * x) + (y * y) + (z * z))

    def __add__(self, other):
        if other.__class__ is Point:                              # O2
            return Point(self.x + other.x, self.y + other.y, self.z + other.z)
        else:
            return Vector(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other):                                     # O2
        return Vector(self.x - other.x, self.y - other.y, self.z - other.z)

    def scale(self, factor):
        return Vector(factor * self.x, factor * self.y, factor * self.z)

    def dot(self, other):                                         # O2
        return (self.x * other.x) + (self.y * other.y) + (self.z * other.z)

    def cross(self, other):                                       # O2
        return Vector(self.y * other.z - self.z * other.y,
                      self.z * other.x - self.x * other.z,
                      self.x * other.y - self.y * other.x)

    def normalized(self):                                         # O4
        x = self.x; y = self.y; z = self.z
        f = 1.0 / sqrt((x * x) + (y * y) + (z * z))
        return Vector(f * x, f * y, f * z)

    def negated(self):
        return self.scale(-1)

    def __eq__(self, other):
        return (self.x == other.x) and (self.y == other.y) and (self.z == other.z)

    def isVector(self):
        return True

    def isPoint(self):
        return False

    def mustBeVector(self):
        return self

    def mustBePoint(self):
        raise 'Vectors are not points!'

    def reflectThrough(self, normal):                             # O4
        nx = normal.x; ny = normal.y; nz = normal.z
        k = (self.x * nx) + (self.y * ny) + (self.z * nz)
        return Vector(self.x - 2 * (k * nx),
                      self.y - 2 * (k * ny),
                      self.z - 2 * (k * nz))


Vector.ZERO = Vector(0, 0, 0)
Vector.RIGHT = Vector(1, 0, 0)
Vector.UP = Vector(0, 1, 0)
Vector.OUT = Vector(0, 0, 1)

assert Vector.RIGHT.reflectThrough(Vector.UP) == Vector.RIGHT
assert Vector(-1, -1, 0).reflectThrough(Vector.UP) == Vector(-1, 1, 0)


class Point(object):
    __slots__ = ('x', 'y', 'z')                                   # O1

    def __init__(self, initx, inity, initz):
        self.x = initx
        self.y = inity
        self.z = initz

    def __str__(self):
        return '(%s,%s,%s)' % (self.x, self.y, self.z)

    def __repr__(self):
        return 'Point(%s,%s,%s)' % (self.x, self.y, self.z)

    def __add__(self, other):                                     # O2
        return Point(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other):
        if other.__class__ is Point:                              # O2
            return Vector(self.x - other.x, self.y - other.y, self.z - other.z)
        else:
            return Point(self.x - other.x, self.y - other.y, self.z - other.z)

    def isVector(self):
        return False

    def isPoint(self):
        return True

    def mustBeVector(self):
        raise 'Points are not vectors!'

    def mustBePoint(self):
        return self


class Sphere(object):

    def __init__(self, centre, radius):
        centre.mustBePoint()
        self.centre = centre
        self.radius = radius

    def __repr__(self):
        return 'Sphere(%s,%s)' % (repr(self.centre), self.radius)

    def intersectionTime(self, ray):                              # O4
        c = self.centre
        p = ray.point
        d = ray.vector
        cx = c.x - p.x
        cy = c.y - p.y
        cz = c.z - p.z
        v = (cx * d.x) + (cy * d.y) + (cz * d.z)
        r = self.radius
        discriminant = (r * r) - (((cx * cx) + (cy * cy) + (cz * cz)) - v * v)
        if discriminant < 0:
            return None
        else:
            return v - sqrt(discriminant)

    def normalAt(self, p):                                        # O4
        c = self.centre
        x = p.x - c.x; y = p.y - c.y; z = p.z - c.z
        f = 1.0 / sqrt((x * x) + (y * y) + (z * z))
        return Vector(f * x, f * y, f * z)


class Halfspace(object):

    def __init__(self, point, normal):
        self.point = point
        self.normal = normal.normalized()

    def __repr__(self):
        return 'Halfspace(%s,%s)' % (repr(self.point), repr(self.normal))

    def intersectionTime(self, ray):                              # O4
        d = ray.vector
        n = self.normal
        v = (d.x * n.x) + (d.y * n.y) + (d.z * n.z)
        if v:
            return 1 / -v
        else:
            return None

    def normalAt(self, p):
        return self.normal


class Ray(object):
    __slots__ = ('point', 'vector')                               # O1

    def __init__(self, point, vector):                            # O4
        self.point = point
        x = vector.x; y = vector.y; z = vector.z
        f = 1.0 / sqrt((x * x) + (y * y) + (z * z))
        self.vector = Vector(f * x, f * y, f * z)

    def __repr__(self):
        return 'Ray(%s,%s)' % (repr(self.point), repr(self.vector))

    def pointAtTime(self, t):                                     # O4
        p = self.point
        v = self.vector
        return Point(p.x + t * v.x, p.y + t * v.y, p.z + t * v.z)


Point.ZERO = Point(0, 0, 0)


class Canvas(object):

    def __init__(self, width, height):
        self.bytes = array.array('B', [0] * (width * height * 3))
        for i in range(width * height):
            self.bytes[i * 3 + 2] = 255
        self.width = width
        self.height = height

    def plot(self, x, y, r, g, b):
        i = ((self.height - y - 1) * self.width + x) * 3
        self.bytes[i] = max(0, min(255, int(r * 255)))
        self.bytes[i + 1] = max(0, min(255, int(g * 255)))
        self.bytes[i + 2] = max(0, min(255, int(b * 255)))

    def write_ppm(self, filename):
        header = 'P6 %d %d 255\n' % (self.width, self.height)
        with open(filename, "wb") as fp:
            fp.write(header.encode('ascii'))
            fp.write(self.bytes.tobytes())


def firstIntersection(intersections):
    result = None
    for i in intersections:
        candidateT = i[1]
        if candidateT is not None and candidateT > -EPSILON:
            if result is None or candidateT < result[1]:
                result = i
    return result


class Scene(object):

    def __init__(self):
        self.objects = []
        self.lightPoints = []
        self.position = Point(0, 1.8, 10)
        self.lookingAt = Point.ZERO
        self.fieldOfView = 45
        self.recursionDepth = 0

    def moveTo(self, p):
        self.position = p

    def lookAt(self, p):
        self.lookingAt = p

    def addObject(self, object, surface):
        self.objects.append((object, surface))

    def addLight(self, p):
        self.lightPoints.append(p)

    def render(self, canvas):
        fovRadians = math.pi * (self.fieldOfView / 2.0) / 180.0
        halfWidth = math.tan(fovRadians)
        halfHeight = 0.75 * halfWidth
        width = halfWidth * 2
        height = halfHeight * 2
        pixelWidth = width / (canvas.width - 1)
        pixelHeight = height / (canvas.height - 1)

        eye = Ray(self.position, self.lookingAt - self.position)
        vpRight = eye.vector.cross(Vector.UP).normalized()
        vpUp = vpRight.cross(eye.vector).normalized()

        # O4: primary-ray direction computed on floats, same operand order as
        #     (eye.vector + vpRight.scale(sx)) + vpUp.scale(sy)
        eyePoint = eye.point
        ex = eye.vector.x; ey = eye.vector.y; ez = eye.vector.z
        rx = vpRight.x; ry = vpRight.y; rz = vpRight.z
        ux = vpUp.x; uy = vpUp.y; uz = vpUp.z
        rayColour = self.rayColour
        plot = canvas.plot
        for y in range(canvas.height):
            sy = y * pixelHeight - halfHeight
            yx = sy * ux; yy = sy * uy; yz = sy * uz
            for x in range(canvas.width):
                sx = x * pixelWidth - halfWidth
                ray = Ray(eyePoint, Vector((ex + sx * rx) + yx,
                                           (ey + sx * ry) + yy,
                                           (ez + sx * rz) + yz))
                colour = rayColour(ray)
                plot(x, y, *colour)

    def rayColour(self, ray):
        if self.recursionDepth > 3:
            return (0, 0, 0)
        try:
            self.recursionDepth = self.recursionDepth + 1
            # O4: closest hit without building a list of tuples
            hitO = None
            hitT = None
            hitS = None
            for (o, s) in self.objects:
                t = o.intersectionTime(ray)
                if t is not None and t > -EPSILON:
                    if hitO is None or t < hitT:
                        hitO = o; hitT = t; hitS = s
            if hitO is None:
                return (0, 0, 0)  # the background colour
            else:
                p = ray.pointAtTime(hitT)
                return hitS.colourAt(self, ray, p, hitO.normalAt(p))
        finally:
            self.recursionDepth = self.recursionDepth - 1

    def _lightIsVisible(self, l, p):
        ray = Ray(p, l - p)                                       # O3: hoisted
        for (o, s) in self.objects:
            t = o.intersectionTime(ray)
            if t is not None and t > EPSILON:
                return False
        return True

    def visibleLights(self, p):
        result = []
        for l in self.lightPoints:
            if self._lightIsVisible(l, p):
                result.append(l)
        return result


def addColours(a, scale, b):
    return (a[0] + scale * b[0],
            a[1] + scale * b[1],
            a[2] + scale * b[2])


class SimpleSurface(object):

    def __init__(self, **kwargs):
        self.baseColour = kwargs.get('baseColour', (1, 1, 1))
        self.specularCoefficient = kwargs.get('specularCoefficient', 0.2)
        self.lambertCoefficient = kwargs.get('lambertCoefficient', 0.6)
        self.ambientCoefficient = 1.0 - self.specularCoefficient - self.lambertCoefficient

    def baseColourAt(self, p):
        return self.baseColour

    def colourAt(self, scene, ray, p, normal):
        b = self.baseColourAt(p)

        c = (0, 0, 0)
        if self.specularCoefficient > 0:
            reflectedRay = Ray(p, ray.vector.reflectThrough(normal))
            reflectedColour = scene.rayColour(reflectedRay)
            c = addColours(c, self.specularCoefficient, reflectedColour)

        if self.lambertCoefficient > 0:
            lambertAmount = 0
            px = p.x; py = p.y; pz = p.z
            nx = normal.x; ny = normal.y; nz = normal.z
            for lightPoint in scene.visibleLights(p):
                # O4: (lightPoint - p).normalized().dot(normal) on floats
                x = lightPoint.x - px; y = lightPoint.y - py; z = lightPoint.z - pz
                f = 1.0 / sqrt((x * x) + (y * y) + (z * z))
                contribution = ((f * x) * nx) + ((f * y) * ny) + ((f * z) * nz)
                if contribution > 0:
                    lambertAmount = lambertAmount + contribution
            lambertAmount = min(1, lambertAmount)
            c = addColours(c, self.lambertCoefficient * lambertAmount, b)

        if self.ambientCoefficient > 0:
            c = addColours(c, self.ambientCoefficient, b)

        return c


class CheckerboardSurface(SimpleSurface):

    def __init__(self, **kwargs):
        SimpleSurface.__init__(self, **kwargs)
        self.otherColour = kwargs.get('otherColour', (0, 0, 0))
        self.checkSize = kwargs.get('checkSize', 1)

    def baseColourAt(self, p):
        v = p - Point.ZERO
        # NOTE: the original calls v.scale(1.0 / self.checkSize) and discards
        # the result (a no-op bug). Kept out of the hot path; output unchanged.
        if ((int(abs(v.x) + 0.5)
             + int(abs(v.y) + 0.5)
             + int(abs(v.z) + 0.5)) % 2):
            return self.otherColour
        else:
            return self.baseColour


def bench_raytrace(loops, width, height, filename):
    range_it = range(loops)
    t0 = pyperf.perf_counter()

    for i in range_it:
        canvas = Canvas(width, height)
        s = Scene()
        s.addLight(Point(30, 30, 10))
        s.addLight(Point(-10, 100, 30))
        s.lookAt(Point(0, 3, 0))
        s.addObject(Sphere(Point(1, 3, -10), 2),
                    SimpleSurface(baseColour=(1, 1, 0)))
        for y in range(6):
            s.addObject(Sphere(Point(-3 - y * 0.4, 2.3, -5), 0.4),
                        SimpleSurface(baseColour=(y / 6.0, 1 - y / 6.0, 0.5)))
        s.addObject(Halfspace(Point(0, 0, 0), Vector.UP),
                    CheckerboardSurface())
        s.render(canvas)

    dt = pyperf.perf_counter() - t0

    if filename:
        canvas.write_ppm(filename)
    return dt


def add_cmdline_args(cmd, args):
    cmd.append("--width=%s" % args.width)
    cmd.append("--height=%s" % args.height)
    if args.filename:
        cmd.extend(("--filename", args.filename))


if __name__ == "__main__":
    runner = pyperf.Runner(add_cmdline_args=add_cmdline_args)
    cmd = runner.argparser
    cmd.add_argument("--width",
                     type=int, default=DEFAULT_WIDTH,
                     help="Image width (default: %s)" % DEFAULT_WIDTH)
    cmd.add_argument("--height",
                     type=int, default=DEFAULT_HEIGHT,
                     help="Image height (default: %s)" % DEFAULT_HEIGHT)
    cmd.add_argument("--filename", metavar="FILENAME.PPM",
                     help="Output filename of the PPM picture")

    args = runner.parse_args()
    runner.metadata['description'] = "Simple raytracer (optimized)"
    runner.metadata['raytrace_width'] = args.width
    runner.metadata['raytrace_height'] = args.height

    runner.bench_time_func('raytrace', bench_raytrace,
                           args.width, args.height,
                           args.filename)
