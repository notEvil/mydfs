import hypothesis as hy
import hypothesis.strategies as hys
import py_tools
import os
import collections
import stat
import logging
import itertools as it
ospath = os.path

NAME_ALPHABET = r'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- `=;[]\\\',~!@#$%^&*()+:{}|"<>?'

hy.settings.register_profile('default', print_blob=hy.PrintSettings.ALWAYS, buffer_size=2**16)
hy.settings.load_profile('default')


def _is_sequence(x):
    r = isinstance(x, collections.Sequence) and not isinstance(x, str)
    return r


def repr_object(x, posAttributeNames=None, kwAttributeNames=None):
    '''
    Builds a string representation of an object using a format representing object initialization.

    @param x                 any
    @param posAttributeNames None or iter(str); iterable of attribute names for positional arguments
    @param kwAttributeNames  None or mapping(str: str) or iter(str); mapping of argument name to attribute name for
                             keyword arguments or iterable of attribute names
    @return str
    '''
    args = []

    if posAttributeNames is not None:
        for attributeName in posAttributeNames:
            value = getattr(x, attributeName)
            args.append(repr(value))

    if kwAttributeNames is not None:
        if not isinstance(kwAttributeNames, collections.Mapping):
            kwAttributeNames = collections.OrderedDict((''.join([attributeName[0].lower(), attributeName[1:]]),
                                                        attributeName) for attributeName in kwAttributeNames)

        for argumentName, attributeName in kwAttributeNames.items():
            value = getattr(x, attributeName)
            args.append('{}={}'.format(argumentName, repr(value)))

    r = '{}({})'.format(type(x).__name__, ', '.join(args))
    return r


@hys.composite
def subsets(draw, xx, min_sizes=hys.just(0)):
    '''
    Strategy for generating random subsets of collections.

    @param xx        strategy: collection(any)
    @param min_sizes strategy: int; strategy generating the minimum size of the subset
    @return collection(any)
    '''
    x = draw(xx)
    min_size = draw(min_sizes)

    if len(x) <= min_size:
        return x

    n = draw(hys.integers(min_value=min_size, max_value=len(x)))
    if n == len(x):
        return x

    y = draw(hys.permutations(x))
    r = y[:n]
    return r


@hys.composite
def paths(draw, roots, cache=None):
    '''
    Strategy for generating paths from an existing file system.

    @param roots strategy: str; strategy generating a path which represents the root of a filesystem
    @param cache None or mapping(str: collection(str)); a cache for candidates;
                 the caller is responsible for invalidation
    @return str
    '''

    root = draw(roots)

    paths = _all_paths(root, cache=cache)
    r = draw(hys.sampled_from(paths))
    return r


@py_tools.cached()
def _all_paths(root):
    r = []

    for base, dirNames, fileNames in os.walk(root):
        r.append(base)

        for name in it.chain(dirNames, fileNames):
            path = ospath.join(base, name)
            r.append(path)

    return r


@hys.composite
def accesses(draw, paths):
    '''
    Strategy for generating operations to test for access to paths.

    @param paths strategy: path
    @return str, int; path and mode
    '''

    path = draw(paths)
    amode = draw(_amodes())
    return path, amode


@hys.composite
def _amodes(draw):
    parts = draw(hys.one_of(hys.just(os.F_OK), subsets(hys.just([os.R_OK, os.W_OK, os.X_OK]), min_size=hys.just(1))))

    if parts == os.F_OK:
        return os.F_OK

    r = parts[0]
    for part in parts:
        r |= part

    return r


def directory_subs():
    '''
    Strategy to generate contents of directories recursively.

    @return [_File or _Directory]
    '''

    return hys.lists(hys.recursive(_files(), _directories))


@hys.composite
def _files(draw):
    name = draw(_file_names())
    content = draw(hys.binary())
    mode = draw(_modes())
    times = draw(_times())
    r = _File(name, content, mode, times)
    return r


class _File:
    def __init__(self, name, content, mode, times):
        self.Name = name
        self.Content = content
        self.Mode = mode
        self.Times = times

    def create(self, base):
        '''
        @param base str; path to base directory
        @return None
        '''
        path = ospath.join(base, self.Name)

        with open(path, 'wb') as f:
            f.write(self.Content)

        os.utime(path, times=self.Times)
        os.chmod(path, self.Mode)

    def __repr__(self):
        return repr_object(self, kwAttributeNames=['Name', 'Content', 'Mode', 'Times'])


@hys.composite
def _directories(draw, subs):
    name = draw(_file_names())
    mode = draw(_modes())
    times = draw(_times())

    subs = draw(hys.lists(subs))

    subs = {sub.Name: sub for sub in subs}
    subs = list(subs.values())

    r = _Directory(name, mode, times, subs)
    return r


class _Directory:
    def __init__(self, name, mode, times, subs):
        self.Name = name
        self.Mode = mode
        self.Times = times
        self.Subs = subs

    def create(self, base):
        '''
        Creates the directory recursively.

        @param base str; path to base directory
        @return None
        '''
        path = ospath.join(base, self.Name)

        os.mkdir(path)
        os.chmod(path, stat.S_IRWXU)

        for sub in self.Subs:
            sub.create(path)

        os.utime(path, times=self.Times)
        os.chmod(path, self.Mode)

    def __repr__(self):
        return repr_object(self, kwAttributeNames=['Name', 'Mode', 'Times', 'Subs'])


@hys.composite
def _file_names(draw):
    # characters = draw(hys.lists(hys.characters(blacklist_characters='/\0', blacklist_categories=['Cs']), min_size=1))
    # r = ''.join(characters)
    r = draw(hys.text(alphabet=NAME_ALPHABET, min_size=1))
    return r


@hys.composite
def _modes(draw):
    parts = draw(subsets(hys.just([stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR])))

    if len(parts) == 0:
        return 0

    r = parts[0]
    for part in parts:
        r |= part

    return r


@hys.composite
def _times(draw):
    atime, mtime = draw(hys.tuples(*[hys.floats(allow_nan=False, min_value=-(2**32), max_value=2**32 - 1)] * 2))
    if atime < mtime:
        atime, mtime = mtime, atime

    return atime, mtime


@hys.composite
def directory_subs_subsets(draw, directorySubs):
    '''
    Strategy to generate subsets of directory contents recursively.

    @param directorySubs strategy: collection(_File or _Directory), see `directory_subs`
    @return [_File or _Directory]
    '''

    directorySubs = draw(directorySubs)
    random = draw(hys.randoms())

    r = _directory_subs_subsets(directorySubs, random, draw)
    return r


def _directory_subs_subsets(subs, random, draw):
    r = []

    for sub in subs:
        if random.random() < 0.5:
            continue

        if isinstance(sub, _File):
            if random.random() < 0.5:
                n = sub

            else:
                nContent = sub.Content if random.random() < 0.5 else draw(hys.binary())
                nMode = sub.Mode if random.random() < 0.5 else draw(_modes())
                nTimes = sub.Times if random.random() < 0.5 else draw(_times())
                n = _File(sub.Name, nContent, nMode, nTimes)

            r.append(n)
            continue

        if random.random() < 0.5:
            nMode = sub.Mode
            nTimes = sub.Times
            nSubs = sub.Subs

        else:
            nMode = sub.Mode if random.random() < 0.5 else draw(_modes())
            nTimes = sub.Times if random.random() < 0.5 else draw(_times())
            nSubs = _directory_subs_subsets(sub.Subs, random, draw)

        n = _Directory(sub.Name, nMode, nTimes, nSubs)
        r.append(n)

    return r


@hys.composite
def directory_subs_subsets2(draw, directorySubs, nn):
    '''
    Strategy to generate multiple subsets of directory contents recursively.

    @param directorySubs strategy: collection(_File or _Directory); strategy generating directory contents
    @param nn            strategy: int; strategy generating the number of subsets
    @return [[_File or _Directory]]
    '''
    directorySubs = draw(directorySubs)
    n = draw(nn)

    if len(directorySubs) == 0:
        return [[] for _ in range(n)]

    random = draw(hys.randoms())

    r = _directory_subs_subsets2(directorySubs, list(range(n)), random, draw)
    r = [r[i] for i in range(n)]
    return r


def _directory_subs_subsets2(subs, indices, random, draw):
    r = {index: [] for index in indices}

    for sub in subs:
        nIndices = draw(subsets(hys.just(indices), min_sizes=hys.just(1)))

        if len(nIndices) == 1:
            nIndex, = nIndices
            r[nIndex].append(sub)
            continue

        isFile = isinstance(sub, _File)

        for i, nIndex in enumerate(nIndices):
            ri = r[nIndex]

            if isFile:
                if i == 0 or random.random() < 0.5:
                    n = sub

                else:
                    nContent = sub.Content if random.random() < 0.5 else draw(hys.binary())
                    nMode = sub.Mode if random.random() < 0.5 else draw(_modes())
                    nTimes = sub.Times if random.random() < 0.5 else draw(_times())
                    n = _File(sub.Name, nContent, nMode, nTimes)

                ri.append(n)
                continue

            if i == 0 or random.random() < 0.5:
                nMode = sub.Mode
                nTimes = sub.Times

            else:
                nMode = sub.Mode if random.random() < 0.5 else draw(_modes())
                nTimes = sub.Times if random.random() < 0.5 else draw(_times())

            n = _Directory(sub.Name, nMode, nTimes, None)
            ri.append(n)

        if isFile:
            continue

        nSubs = _directory_subs_subsets2(sub.Subs, nIndices, random, draw)

        for nIndex in nIndices:
            r[nIndex][-1].Subs = nSubs[nIndex]

    return r
