import os
import itertools as it

ospath = os.path


class Assert:
    def __init__(self, path):
        self.Path = path

    def assert_(self):
        raise NotImplementedError

    def _on_error(self, expected, got):
        print('for path', self.Path)
        print('expected', repr(expected))
        print('got', repr(got))

        if type(expected) == type(got):
            print('difference ', end='')
            if type(expected) == set:
                print('rem:', repr(expected - got), 'add:', repr(got - expected))
            elif type(expected) == dict:
                print('rem:', {k: expected[k] for k in expected.keys() - got.keys()},
                      'dif:', {k: (expected[k], got[k])
                               for k in expected.keys() & got.keys() if expected[k] != got[k]},
                      'add:', {k: got[k] for k in got.keys() - expected.keys()})

    def __hash__(self):
        return hash((type(self), self.Path))

    def __eq__(self, other):
        return type(self) == type(other) and self.Path == other.Path


def buildAssertForFunction(f, name):
    class AssertFunction(Assert):
        def __init__(self, path, expected):
            super().__init__(path)

            self.Expected = expected

        def assert_(self):
            n = f(self.Path)
            try:
                assert n == self.Expected
            except:
                print('in', name)
                self._on_error(self.Expected, n)
                raise

    AssertFunction.__name__ = name
    return AssertFunction


# AssertAccess?


def getTree(path):
    r = []
    for base, dirs, files in os.walk(path):
        for name in it.chain(dirs, files):
            r.append(ospath.join(base, name))
    return set(r)


AssertTree = buildAssertForFunction(getTree, 'AssertTree')


class AssertTree(AssertTree):
    def add(self, path):
        self.Expected.add(path)

    def remove(self, path):
        self.Expected.remove(path)


def getContent(path):
    with open(path, 'rb') as f:
        r = f.read()
    return r


AssertContent = buildAssertForFunction(getContent, 'AssertContent')


if False:
    def getStat(path):
        st = os.lstat(path)
        return {n: getattr(st, n)
                for n in ['st_mode', 'st_nlink', 'st_uid', 'st_gid', 'st_size', 'st_mtime']}  # , 'st_atime', ]}

    AssertStat = buildAssertForFunction(getStat, 'AssertStat')

    class AssertStat(AssertStat):
        def setMode(self, mode):
            self.Expected['st_mode'] = mode

        def setOwner(self, uid, gid):
            self.Expected['st_uid'] = uid
            self.Expected['st_gid'] = gid

        def setSize(self, size):
            self.Expected['st_size'] = size

        def setMtime(self, mtime):
            self.Expected['st_mtime'] = mtime

else:
    StatAsserts = {}

    def getMode(path):
        return os.lstat(path).st_mode

    AssertMode = buildAssertForFunction(getMode, 'AssertMode')
    StatAsserts[AssertMode] = getMode

    def getOwner(path):
        st = os.lstat(path)
        return st.st_uid, st.st_gid

    AssertOwner = buildAssertForFunction(getOwner, 'AssertOwner')
    StatAsserts[AssertOwner] = getOwner

    def getSize(path):
        return os.lstat(path).st_size

    AssertSize = buildAssertForFunction(getSize, 'AssertSize')
    StatAsserts[AssertSize] = getSize

    def getMtime(path):
        return os.lstat(path).st_mtime

    AssertMtime = buildAssertForFunction(getMtime, 'AssertMtime')
    StatAsserts[AssertMtime] = getMtime


def getSymlinkTarget(path):
    return os.readlink(path)


AssertSymlinkTarget = buildAssertForFunction(getSymlinkTarget, 'AssertSymlinkTarget')


# AssertMtime? AssertAtime?
