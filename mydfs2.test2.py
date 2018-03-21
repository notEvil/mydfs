import test_base
import collections
import os
import shutil
import time
import subprocess as sub
import sys
import signal
import random
import itertools as it
import pwd
from pprint import pprint

ospath = os.path


# def sadd(x, s):
# s.discard(x)
# s.add(x)


def randomName(n=10):
    az = ''.join(chr(x) for x in range(ord('a'), ord('z') + 1))
    cc = ''.join([az, az.upper(), '0123456789', '_. '])
    return ''.join(random.choice(cc) for i in range(n))


# define environment
EnvR = 'mydfs2.test2'


class SameFile(str):
    pass


SameMtime = collections.namedtuple('SameMtime', ['Content', 'Other'])


Env = {
    EnvR + '/s1': None,
    EnvR + '/s1/f1': b'content',
    EnvR + '/s1/d1': None,
    EnvR + '/s1/d1/g1': b'g1',
    EnvR + '/s1/f12': b'same content',
    EnvR + '/s1/d12': None,
    EnvR + '/s1/d12/g12': b'different mtime',
    EnvR + '/s1/d12/h12': b'different content',
    EnvR + '/s2': None,
    EnvR + '/s2/f2': b'other content',
    EnvR + '/s2/d2': None,
    EnvR + '/s2/d2/g2': b'g2',
    EnvR + '/s2/f12': SameFile(EnvR + '/s1/f12'),
    EnvR + '/s2/d12': None,
    EnvR + '/s2/d12/g12': b'different mtime',
    EnvR + '/s2/d12/h12': SameMtime(Content=b'different cont', Other=EnvR + '/s1/d12/h12'),
    # EnvR + '/target': None,
}

Sources = [('a', EnvR + '/s1'), ('b', EnvR + '/s2')]
Target = EnvR + '/target'
#


# define asserts
Asserts = {}

tree = set()
tree.update(Env.keys())  # source dirs and files
tree.update({Target + path for path in ['', '/a._f1', '/d1', '/d1/a._g1', '/ab_f12', '/d12',
                                        '/d12/a._g12', '/d12/a._h12', '/.b_f2', '/d2', '/d2/.b_g2', '/d12/.b_g12',
                                        '/d12/.b_h12']})  # target dirs and files
Asserts[test_base.AssertTree] = test_base.AssertTree(EnvR, tree)

TargetMap = {
    Target + '/a._f1': [EnvR + '/s1/f1'],
    Target + '/d1': [EnvR + '/s1/d1'],
    Target + '/d1/a._g1': [EnvR + '/s1/d1/g1'],
    Target + '/ab_f12': [EnvR + '/s1/f12', EnvR + '/s2/f12'],
    Target + '/d12': [EnvR + '/s1/d12', EnvR + '/s2/d12'],
    Target + '/d12/a._g12': [EnvR + '/s1/d12/g12'],
    Target + '/d12/a._h12': [EnvR + '/s1/d12/h12'],
    Target + '/.b_f2': [EnvR + '/s2/f2'],
    Target + '/d2': [EnvR + '/s2/d2'],
    Target + '/d2/.b_g2': [EnvR + '/s2/d2/g2'],
    Target + '/d12/.b_g12': [EnvR + '/s2/d12/g12'],
    Target + '/d12/.b_h12': [EnvR + '/s2/d12/h12'],
}

contents = {}
contents.update({path: data if type(data) == bytes else (Env[data] if type(data) == SameFile else data.Content)
                 for path, data in Env.items() if data is not None})  # source contents
contents.update({path: contents[others[0]] for path, others in TargetMap.items()
                 if Env[others[0]] is not None})  # target contents
Asserts.update({(path, test_base.AssertContent): test_base.AssertContent(path, content)
                for path, content in contents.items()})


def initAsserts(asserts):
    '''
    - assumes env to exist
    - updates asserts
    '''
    for path in Env.keys():  # source stats
        for Assert, get in test_base.StatAsserts.items():
            asserts[(path, Assert)] = Assert(path, get(path))

    for Assert, get in test_base.StatAsserts.items():  # /s2/f12 stats
        asserts[(path, Assert)] = Assert(EnvR + '/s2/f12', get(EnvR + '/s1/f12'))

    path = EnvR + '/s2/d12/h12'
    asserts[(path, test_base.AssertMtime)] = test_base.AssertMtime(
        path, test_base.getMtime(EnvR + '/s1/d12/h12'))  # /s2/d12/h12

    for path, others in TargetMap.items():  # target stats
        for Assert, get in test_base.StatAsserts.items():
            asserts[(path, Assert)] = Assert(path, get(others[0]))
#


def buildEnv():
    if ospath.exists(EnvR):
        raise Exception('test env directory exists')

    os.mkdir(EnvR)

    # create directories
    for path, data in Env.items():
        if data is not None:
            continue

        os.makedirs(path, exist_ok=True)

    # create files
    for path, data in Env.items():
        if not (type(data) == bytes):
            continue

        time.sleep(0.005)
        with open(path, 'wb') as f:
            f.write(data)

    # else
    for path, data in Env.items():
        if type(data) == SameFile:
            shutil.copy2(data, path)

        elif type(data) == SameMtime:
            with open(path, 'wb') as f:
                f.write(data.Content)

            shutil.copystat(data.Other, path)

    # create target
    os.mkdir(Target)


def mountMydfs2():
    args = [sys.executable, 'mydfs2.py']
    args.extend('{}={}'.format(c, path) for c, path in Sources)
    args.append(Target)
    p = sub.Popen(args)
    time.sleep(1)
    return p


tests = set()


def test_init(asserts):
    input('waiting ')


tests.add(test_init)


def test_chmod(asserts):
    for base, dirs, files in os.walk(Target):
        for name in it.chain(dirs, files):
            if random.random() < 0.25:
                continue

            path = ospath.join(base, name)
            mode = os.lstat(path).st_mode
            mode = ((mode >> 9) << 9) | random.getrandbits(9)
            # print(mode, path)
            os.chmod(path, mode)

            asserts[(path, test_base.AssertMode)] = test_base.AssertMode(path, mode)
            for other in TargetMap[path]:
                asserts[(other, test_base.AssertMode)] = test_base.AssertMode(other, mode)


tests.add(test_chmod)


def test_chown(asserts):
    for base, dirs, files in os.walk(Target):
        for name in it.chain(dirs, files):
            if random.random() < 0.25:
                continue

            path = ospath.join(base, name)
            t = random.choice(pwd.getpwall())
            uid = t.pw_uid
            gid = t.pw_gid
            os.chown(path, uid, gid)

            asserts[(path, test_base.AssertOwner)] = test_base.AssertOwner(path, (uid, gid))
            for other in TargetMap[path]:
                asserts[(other, test_base.AssertOwner)] = test_base.AssertOwner(other, (uid, gid))


tests.add(test_chown)


def test_create(asserts):
    for base, dirs, files in os.walk(Target):
        for name in dirs:
            if random.random() < 0.25:
                continue

            # prepare
            dirPath = ospath.join(base, name)

            names = os.listdir(dirPath)
            if random.random() < 0.5 and len(names) != 0:
                name = random.choice(names)
                overwrite = True
            else:
                while True:
                    name = randomName()
                    path = ospath.join(dirPath, name)
                    if not ospath.exists(path):
                        break
                overwrite = False

            path = ospath.join(dirPath, name)

            if random.random() < 0.5:
                content = os.urandom(random.randrange(1, 1024 + 1))
            else:
                content = b''

            # do
            with open(path, 'wb') as f:
                f.write(content)

            # assert
            if overwrite:
                mtime = test_base.getMtime(path)
                asserts.pop((path, test_base.AssertMtime), None)
                # for other in TargetMap[path]:
                # asserts[(other, test_base.AssertMtime)] = test_base.AssertMtime(other, mtime)
            else:
                a = asserts[test_base.AssertTree]
                # a.add(


tests.add(test_create)


def assert_(asserts):
    for a in asserts.values():
        a.assert_()


def unmountMydfs2(proc):
    proc.send_signal(signal.SIGINT)
    proc.wait()


def destroyEnv():
    shutil.rmtree(EnvR)


# main
for test in tests:
    buildEnv()

    asserts = Asserts.copy()
    initAsserts(asserts)

    proc = mountMydfs2()

    try:
        test(asserts)
        assert_(asserts)

    finally:
        unmountMydfs2(proc)

    destroyEnv()
#
