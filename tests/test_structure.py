"""Guards on how the window is put together."""
import collections, glob, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_method_is_defined_by_two_parts_of_the_window():
    """AssistantWindow is assembled from mixins. If two of them define the same method, one silently wins
    (this once turned 'switch to Coder mode' into 'switch to bubble mode')."""
    defs = collections.defaultdict(list)
    for path in sorted(glob.glob(os.path.join(ROOT, "win_*.py"))) + [os.path.join(ROOT, "main.py")]:
        cls = None
        for line in open(path, encoding="utf-8"):
            m = re.match(r"class (\w+)", line)
            if m: cls = m.group(1)
            m = re.match(r"    def (\w+)\(", line)
            if m and cls and (cls.endswith("Mixin") or cls == "AssistantWindow"):
                defs[m.group(1)].append(f"{os.path.basename(path)}:{cls}")
    clashes = {name: where for name, where in defs.items() if len(where) > 1}
    assert not clashes, clashes


def test_every_mixin_is_part_of_the_window():
    import main
    bases = {b.__name__ for b in main.AssistantWindow.__mro__}
    for path in glob.glob(os.path.join(ROOT, "win_*.py")):
        for cls in re.findall(r"^class (\w+Mixin)", open(path, encoding="utf-8").read(), re.M):
            assert cls in bases, f"{cls} ({os.path.basename(path)}) is not used by AssistantWindow"
