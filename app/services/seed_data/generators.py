"""Deterministic generators for original, computation-based LET-style items with worked rationalizations.

Every item is produced from random parameters (fixed seed), so stems and numbers are original by construction.
Output format matches questions.py: (stem, A, B, C, D, correct, rationalization, difficulty, competency).
"""
import math
import random
from fractions import Fraction

LETTERS = "ABCD"


def _pack(rng: random.Random, stem: str, correct, wrong: list, why: str, diff: str, comp: str, fmt=str) -> tuple | None:
    options, seen = [], set()
    for v in [correct] + wrong:
        s = fmt(v)
        if s not in seen:
            seen.add(s)
            options.append(s)
    if len(options) < 4:
        return None
    options = options[:4]
    key_text = options[0]
    rng.shuffle(options)
    letter = LETTERS[options.index(key_text)]
    others = ", ".join(f"{LETTERS[i]} ({o})" for i, o in enumerate(options) if o != key_text)
    rationale = f"{letter} is correct: {why} The other options — {others} — come from common computation errors."
    return (stem, *options, letter, rationale, diff, comp)


def _money(v) -> str:
    return f"₱{v:,.2f}".replace(".00", "")


def number_sense(rng):
    out = []
    for _ in range(8):
        p, n = rng.choice([5, 12, 15, 25, 35, 40, 60, 75]), rng.choice([80, 120, 240, 360, 480, 640, 720])
        ans = p * n / 100
        out.append(_pack(rng, f"What is {p}% of {n}?", ans, [n * 100 / p if p else 0, ans * 10, n - ans],
                         f"{p}% of {n} = {p}/100 × {n} = {ans:g}.", "easy", "Percent", lambda v: f"{v:g}"))
    for _ in range(6):
        price, d = rng.choice([280, 450, 640, 850, 1200, 1500]), rng.choice([10, 15, 20, 25, 30])
        ans = price * (100 - d) / 100
        out.append(_pack(rng, f"A school bag costs {_money(price)}. During a sale it is {d}% off. What is the sale price?",
                         ans, [price * d / 100, price + price * d / 100, price - d],
                         f"Discount = {d}% × {price} = {price * d / 100:g}; sale price = {price} − {price * d / 100:g} = {ans:g}.",
                         "easy", "Percent applications", _money))
    for _ in range(6):
        g = rng.choice([4, 6, 8, 9, 12, 14, 15])
        a, b = g * rng.choice([2, 3, 5]), g * rng.choice([7, 11, 4])
        if math.gcd(a, b) != g:
            continue
        lcm = a * b // g
        out.append(_pack(rng, f"What is the greatest common factor of {a} and {b}?", g, [lcm, g // 2 or 1, g * 2],
                         f"The largest number dividing both {a} and {b} is {g}; {lcm} is their LCM.", "easy", "GCF and LCM"))
    for _ in range(6):
        a, b = rng.choice([(4, 6), (6, 9), (8, 12), (10, 15), (12, 18), (9, 12), (14, 21), (15, 20)])
        g = math.gcd(a, b)
        lcm = a * b // g
        out.append(_pack(rng, f"What is the least common multiple of {a} and {b}?", lcm, [a * b, g, lcm * 2],
                         f"LCM = ({a} × {b}) ÷ GCF({g}) = {lcm}.", "medium", "GCF and LCM"))
    for _ in range(6):
        f1 = Fraction(rng.randint(1, 4), rng.choice([3, 4, 5, 6]))
        f2 = Fraction(rng.randint(1, 4), rng.choice([2, 3, 8]))
        ans = f1 + f2
        naive = Fraction(f1.numerator + f2.numerator, f1.denominator + f2.denominator)
        out.append(_pack(rng, f"What is {f1} + {f2} in lowest terms?", ans, [naive, f1 * f2, ans + Fraction(1, 2)],
                         f"Use a common denominator: {f1} + {f2} = {ans}.", "medium", "Operations on fractions"))
    return out


def algebra(rng):
    out = []
    for _ in range(15):
        a, x, b = rng.randint(2, 9), rng.randint(-6, 12), rng.randint(-15, 20)
        c = a * x + b
        bs = f"+ {b}" if b >= 0 else f"− {-b}"
        out.append(_pack(rng, f"Solve for x: {a}x {bs} = {c}", x, [(c + b) / a, c / a - b, -x if x else x + 1],
                         f"Subtract {b} from both sides to get {a}x = {c - b}, then divide by {a}: x = {x}.", "easy",
                         "Linear equations", lambda v: f"{v:g}" if isinstance(v, float) else str(v)))
    for _ in range(10):
        x, y = rng.randint(-4, 6), rng.randint(1, 5)
        a, b = rng.randint(2, 5), rng.randint(1, 4)
        val = a * x * x - b * y
        out.append(_pack(rng, f"Evaluate {a}x² − {b}y when x = {x} and y = {y}.", val,
                         [(a * x) ** 2 - b * y, a * x * 2 - b * y, a * x * x + b * y],
                         f"{a}({x})² − {b}({y}) = {a * x * x} − {b * y} = {val}.", "medium", "Evaluating expressions"))
    return out


def geometry(rng):
    out = []
    for _ in range(10):
        length, w = rng.randint(6, 25), rng.randint(3, 15)
        if length == w:
            continue
        out.append(_pack(rng, f"A rectangular garden is {length} m long and {w} m wide. What is its perimeter?",
                         2 * (length + w), [length * w, length + w, 4 * length],
                         f"P = 2(l + w) = 2({length} + {w}) = {2 * (length + w)} m.", "easy", "Perimeter",
                         lambda v: f"{v} m"))
        out.append(_pack(rng, f"What is the area of a rectangle {length} cm long and {w} cm wide?", length * w,
                         [2 * (length + w), length * w * 2, length + w],
                         f"A = l × w = {length} × {w} = {length * w} cm².", "easy", "Area", lambda v: f"{v} cm²"))
    for _ in range(5):
        r = rng.choice([2, 3, 5, 7, 10])
        area = round(3.14 * r * r, 2)
        out.append(_pack(rng, f"Using π = 3.14, what is the area of a circle with radius {r} cm?", area,
                         [round(2 * 3.14 * r, 2), round(3.14 * (2 * r) ** 2, 2), round(3.14 * r, 2)],
                         f"A = πr² = 3.14 × {r}² = {area:g} cm².", "medium", "Area of circles",
                         lambda v: f"{v:g} cm²"))
    for _ in range(10):
        a, b = rng.randint(25, 85), rng.randint(25, 85)
        if a + b >= 170:
            continue
        out.append(_pack(rng, f"Two angles of a triangle measure {a}° and {b}°. What is the third angle?", 180 - a - b,
                         [360 - a - b, 90 - (a + b) % 90 or 45, a + b],
                         f"The angles of a triangle add up to 180°: 180 − {a} − {b} = {180 - a - b}°.", "easy",
                         "Angles of triangles", lambda v: f"{v}°"))
    return out


def statistics(rng):
    out = []
    for _ in range(10):
        data = sorted(rng.sample(range(60, 100), 5))
        mean = sum(data) / 5
        out.append(_pack(rng, f"Find the mean of the scores {', '.join(map(str, data))}.", mean,
                         [data[2], (data[0] + data[-1]) / 2 + 3, sum(data) / 4],
                         f"Mean = {sum(data)} ÷ 5 = {mean:g}.", "easy", "Measures of central tendency",
                         lambda v: f"{v:g}"))
    for _ in range(8):
        data = rng.sample(range(10, 60), 7)
        s = sorted(data)
        out.append(_pack(rng, f"What is the median of {', '.join(map(str, data))}?", s[3], [data[3], s[2], s[4]],
                         f"Arrange in order ({', '.join(map(str, s))}); the middle (4th) value is {s[3]}.", "medium",
                         "Measures of central tendency"))
    for _ in range(5):
        mode = rng.randint(2, 9)
        others = rng.sample([v for v in range(1, 12) if v != mode], 4)
        data = others + [mode] * 3
        rng.shuffle(data)
        out.append(_pack(rng, f"What is the mode of {', '.join(map(str, data))}?", mode,
                         [max(data), min(data), round(sum(data) / len(data))],
                         f"{mode} appears most often (3 times).", "easy", "Measures of central tendency"))
    for _ in range(10):
        red, blue, green = rng.randint(2, 8), rng.randint(2, 8), rng.randint(1, 6)
        total = red + blue + green
        ans = Fraction(red, total)
        out.append(_pack(rng, f"A bag has {red} red, {blue} blue and {green} green marbles. If one marble is drawn at "
                              f"random, what is the probability that it is red?", ans,
                         [Fraction(red, blue + green), Fraction(blue + green, total), Fraction(1, 3)],
                         f"P(red) = {red}/{total} = {ans}.", "medium", "Probability"))
    return out


def assessment_stats(rng):
    out = []
    for _ in range(6):
        data = rng.sample(range(15, 50), 6)
        out.append(_pack(rng, f"A class's quiz scores are {', '.join(map(str, data))}. What is the range?",
                         max(data) - min(data), [max(data), max(data) - min(data) + 1, sum(data) // 6],
                         f"Range = highest − lowest = {max(data)} − {min(data)} = {max(data) - min(data)}.", "easy",
                         "Measures of variability"))
    for _ in range(8):
        mean, sd, k = rng.choice([70, 75, 80, 50]), rng.choice([4, 5, 8, 10]), rng.choice([-2, -1, 1, 1.5, 2])
        x = mean + k * sd
        out.append(_pack(rng, f"In a test with mean {mean} and standard deviation {sd}, what is the z-score of a raw "
                              f"score of {x:g}?", k, [x - mean, (x - mean) / mean, -k],
                         f"z = (X − mean) ÷ SD = ({x:g} − {mean}) ÷ {sd} = {k:g}.", "medium", "Standard scores",
                         lambda v: f"{v:g}"))
    for _ in range(6):
        n, right = rng.choice([20, 25, 40, 50]), None
        right = rng.randint(n // 4, n - 1)
        p = right / n
        out.append(_pack(rng, f"{right} of {n} examinees answered an item correctly. What is its difficulty index?",
                         round(p, 2), [round(1 - p, 2), right, round(n / right, 2)],
                         f"p = number correct ÷ number of examinees = {right}/{n} = {p:.2f}.", "medium", "Item analysis",
                         lambda v: f"{v:g}"))
    return out


def major_prob_stats(rng):
    out = []
    for _ in range(8):
        n, r = rng.randint(5, 10), rng.randint(2, 4)
        ans = math.comb(n, r)
        out.append(_pack(rng, f"In how many ways can a committee of {r} be chosen from {n} teachers?", ans,
                         [math.perm(n, r), n * r, math.comb(n, r - 1) if r > 1 else n],
                         f"Order does not matter, so use C({n},{r}) = {ans}.", "medium", "Combinations"))
    for _ in range(6):
        n, r = rng.randint(5, 9), rng.randint(2, 3)
        ans = math.perm(n, r)
        out.append(_pack(rng, f"How many ways can {r} different prizes be awarded to {n} contestants (one prize each)?",
                         ans, [math.comb(n, r), n ** r if n ** r != ans else ans + 1, n * r],
                         f"Order matters, so use P({n},{r}) = {ans}.", "medium", "Permutations"))
    return out


def calculus(rng):
    out = []
    for _ in range(10):
        a, n, x = rng.randint(2, 6), rng.randint(2, 4), rng.randint(1, 3)
        ans = a * n * x ** (n - 1)
        out.append(_pack(rng, f"If f(x) = {a}x^{n}, what is f′({x})?", ans, [a * x ** n, a * n * x ** n, n * x ** (n - 1)],
                         f"f′(x) = {a * n}x^{n - 1}, so f′({x}) = {a * n}·{x}^{n - 1} = {ans}.", "medium",
                         "Derivatives"))
    for _ in range(6):
        a, b = rng.randint(1, 3), rng.randint(2, 5)
        ans = Fraction(a * b ** 3, 3)
        out.append(_pack(rng, f"Evaluate the definite integral of {a}x² from 0 to {b}.", ans,
                         [Fraction(a * b ** 2, 2), a * b ** 3, Fraction(2 * a * b)],
                         f"∫{a}x² dx = {a}x³/3; from 0 to {b} gives {a}·{b}³/3 = {ans}.", "hard", "Integrals"))
    return out


def geo_trig(rng):
    out = []
    for a, b, c in [(3, 4, 5), (5, 12, 13), (8, 15, 17), (6, 8, 10), (7, 24, 25), (9, 12, 15), (12, 16, 20), (20, 21, 29)]:
        out.append(_pack(rng, f"A right triangle has legs {a} cm and {b} cm. How long is the hypotenuse?", c,
                         [a + b, round(math.sqrt(b * b - a * a), 2) if b > a else c + 1, c + 2],
                         f"c = √({a}² + {b}²) = √{a * a + b * b} = {c} cm.", "easy", "Pythagorean theorem",
                         lambda v: f"{v:g} cm"))
    for n in rng.sample([5, 6, 7, 8, 9, 10, 12], 6):
        ans = (n - 2) * 180
        out.append(_pack(rng, f"What is the sum of the interior angles of a polygon with {n} sides?", ans,
                         [n * 180, 360, (n - 1) * 180], f"Sum = (n − 2) × 180° = ({n} − 2) × 180° = {ans}°.", "easy",
                         "Polygons", lambda v: f"{v}°"))
    return out


def adv_algebra(rng):
    out = []
    for _ in range(8):
        a1, d, n = rng.randint(-5, 10), rng.randint(2, 7), rng.randint(10, 30)
        ans = a1 + (n - 1) * d
        out.append(_pack(rng, f"What is term {n} of the arithmetic sequence {a1}, {a1 + d}, {a1 + 2 * d}, …?", ans,
                         [a1 + n * d, a1 * d * n, ans - d + 1],
                         f"aₙ = a₁ + (n − 1)d = {a1} + {n - 1}({d}) = {ans}.", "medium", "Arithmetic sequences"))
    for _ in range(6):
        a1, r, n = rng.randint(1, 4), rng.choice([2, 3]), rng.randint(5, 8)
        ans = a1 * r ** (n - 1)
        out.append(_pack(rng, f"What is term {n} of the geometric sequence {a1}, {a1 * r}, {a1 * r * r}, …?", ans,
                         [a1 * r ** n, a1 * r * n, ans // r + a1], f"aₙ = a₁·r^(n−1) = {a1}·{r}^{n - 1} = {ans}.",
                         "medium", "Geometric sequences"))
    return out


GENERATORS = {
    ("Mathematics", "Number Sense and Operations"): number_sense,
    ("Mathematics", "Algebra"): algebra,
    ("Mathematics", "Geometry and Measurement"): geometry,
    ("Mathematics", "Statistics and Probability"): statistics,
    ("Assessment of Learning", "Statistics in Assessment"): assessment_stats,
    ("Mathematics Major", "Probability and Statistics"): major_prob_stats,
    ("Mathematics Major", "Calculus"): calculus,
    ("Mathematics Major", "Geometry and Trigonometry"): geo_trig,
    ("Mathematics Major", "Advanced Algebra and Number Theory"): adv_algebra,
}


def generated_questions(seed: int = 2026) -> dict[tuple[str, str], list[tuple]]:
    out = {}
    for key, gen in GENERATORS.items():
        rng = random.Random(f"{seed}:{key}")
        out[key] = [q for q in gen(rng) if q]
    return out
