import os
import shutil
import collections
import time
import subprocess as sub
import sys
import signal
import random

ospath = os.path


EnvBaseDir = 'mydfs2.test'


class SameFile(str):
    pass


SameMtime = collections.namedtuple('SameMtime', ['Content', 'OtherFile'])


# all tests rely on this env !
Env = {
    '/s1': None,
    '/s1/f1': 'content',
    '/s1/f12': 'same content',
    '/s1/d1': None,
    '/s1/d1/g1': 'g1',
    '/s1/d12': None,
    '/s1/d12/g12': 'different mtime',
    '/s1/d12/h12': 'different content',
    '/s2': None,
    '/s2/f2': 'other content',
    '/s2/f12': SameFile('/s1/f12'),
    '/s2/d2': None,
    '/s2/d2/g2': 'g2',
    '/s2/d12': None,
    '/s2/d12/g12': 'different mtime',
    '/s2/d12/h12': SameMtime(Content='different cont', OtherFile='/s1/d12/g12'),
    '/target': None,
}
Sources = [('a', '/s1'), ('b', '/s2')]
Target = '/target'

EnvMap = {
    '/s1': Target + '/',
    '/s1/f1': Target + '/a._f1',
    '/s1/f12': Target + '/ab_f12',
    '/s1/d1': Target + '/d1',
    '/s1/d1/g1': Target + '/d1/a._g1',
    '/s1/d12': Target + '/d12',
    '/s1/d12/g12': Target + '/d12/a._g12',
    '/s1/d12/h12': Target + '/d12/a._h12',
    '/s2': Target + '/',
    '/s2/f2': Target + '/.b_f2',
    '/s2/f12': Target + '/ab_f12',
    '/s2/d2': Target + '/d2',
    '/s2/d2/g2': Target + '/d2/.b_g2',
    '/s2/d12': Target + '/d12',
    '/s2/d12/g12': Target + '/d12/.b_g12',
    '/s2/d12/h12': Target + '/d12/.b_h12',
}


def prepareEnv():
    if ospath.exists(EnvBaseDir):
        raise Exception('test env directory exists')

    for path, data in Env.items():
        if data is not None:
            continue

        os.makedirs(EnvBaseDir + path, exist_ok=True)

    for path, data in Env.items():
        if not (type(data) == str):
            continue

        time.sleep(0.002)
        with open(EnvBaseDir + path, 'w') as f:
            f.write(data)

    for path, data in Env.items():
        if type(data) == SameFile:
            shutil.copy2(EnvBaseDir + data, EnvBaseDir + path)

        elif type(data) == SameMtime:
            with open(EnvBaseDir + path, 'w') as f:
                f.write(data.Content)

            shutil.copystat(EnvBaseDir + data.OtherFile, EnvBaseDir + path)

    args = [sys.executable, 'mydfs2.py']
    args.extend('{}={}'.format(c, EnvBaseDir + path) for c, path in Sources)
    args.append(EnvBaseDir + Target)

    p = sub.Popen(args)
    time.sleep(1)

    return p


def destroyEnv(env):
    p = env

    p.send_signal(signal.SIGINT)
    p.wait()
    shutil.rmtree(EnvBaseDir)


def _check(**kwargs):
    for method, d in kwargs.items():
        if method == 'listdir':
            for path, names in d.items():
                assert set(os.listdir(EnvBaseDir + path)) == set(names)
        elif method == 'content':
            for path, content in d.items():
                with open(EnvBaseDir + path, 'r') as f:
                    assert f.read() == content
        elif method == 'chmod':
            for path, mode in d.items():
                t = os.lstat(EnvBaseDir + path).st_mode
                print(path, mode, t)
                assert t == mode
        else:
            raise Exception('unknown method')


def test_init():
    listdir = {}
    for path in EnvMap.values():
        base, name = ospath.split(path)
        if name == '':
            continue
        listdir.setdefault(base, set()).add(name)

    content = {
        Target + '/a._f1': Env['/s1/f1'],
        Target + '/ab_f12': Env['/s1/f12'],
        Target + '/.b_f2': Env['/s2/f2'],
        Target + '/d1/a._g1': Env['/s1/d1/g1'],
        Target + '/d2/.b_g2': Env['/s2/d2/g2'],
        Target + '/d12/a._g12': Env['/s1/d12/g12'],
        Target + '/d12/.b_g12': Env['/s2/d12/g12'],
        Target + '/d12/a._h12': Env['/s1/d12/h12'],
        Target + '/d12/.b_h12': Env['/s2/d12/h12'].Content,
    }
    _check(listdir=listdir, content=content)


def test_chmod():
    chmod = {}

    for path, d in Env.items():
        if d is None:
            continue
        tPath = EnvMap[path]

        mode = random.getrandbits(9)
        os.chmod(EnvBaseDir + tPath, mode)

        chmod[tPath] = mode
        chmod[path] = mode

    _check(chmod=chmod)


env = prepareEnv()
# input()
try:
    test_init()
    test_chmod()
finally:
    destroyEnv(env)
