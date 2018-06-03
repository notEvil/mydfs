import hypothesis.strategies as hys
import os
import shutil
import stat
import pwd
import grp
import tempfile
import itertools as it
ospath = os.path

NAME_ALPHABET = r'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._- `=;[]\\\',~!@#$%^&*()+:{}|"<>?'

#

_UserIds = None


def get_user_ids():
    global _UserIds

    r = _UserIds
    if r is not None:
        return r

    r = set()
    with tempfile.TemporaryFile() as f:
        path = f.name

        os.chmod(path, os.stat(path).st_mode | stat.S_IRWXG)

        for entry in pwd.getpwall():
            uid = entry.pw_uid

            try:
                os.chown(path, uid, -1)

            except PermissionError:
                pass

            else:
                r.add(uid)

    r = sorted(r)

    _UserIds = r
    return r


#

_GroupIds = None


def get_group_ids():
    global _GroupIds

    r = _GroupIds
    if r is not None:
        return r

    r = set()
    with tempfile.TemporaryFile() as f:
        path = f.name

        os.chmod(path, os.stat(path).st_mode | stat.S_IRWXU)

        for gid in it.chain((entry.pw_gid for entry in pwd.getpwall()), (entry.gr_gid for entry in grp.getgrall())):
            try:
                os.chown(path, -1, gid)

            except PermissionError:
                pass

            else:
                r.add(gid)

    r = sorted(r)

    _GroupIds = r
    return r


@hys.composite
def subsets(draw, x, min_size=0):
    if len(x) <= min_size:
        return x

    n = draw(hys.integers(min_value=min_size, max_value=len(x)))
    if n == len(x):
        return x

    y = draw(hys.permutations(x))
    r = y[:n]
    return r


class File:
    def __init__(self, aTime, mTime, user, group, mode):
        self.ATime = aTime
        self.MTime = mTime
        self.User = user
        self.Group = group
        self.Mode = mode

    def create(self, path):
        raise NotImplementedError

    def _create(self, path):
        _stat = None

        def stat_():
            nonlocal _stat
            if _stat is None:
                _stat = os.stat(path)
            return _stat

        if self.ATime is not None or self.MTime is not None:
            aTime = stat_().st_atime_ns if self.ATime is None else self.ATime
            mTime = stat_().st_mtime_ns if self.MTime is None else self.MTime
            os.utime(path, ns=(aTime, mTime))

        if self.User is not None or self.Group is not None:
            user = -1 if self.User is None else self.User
            group = -1 if self.Group is None else self.Group
            os.chown(path, user, group)

        if self.Mode is not None:
            os.chmod(path, self.Mode)

    def assert_(self, path):
        assert ospath.exists(path)

        _stat = None

        def stat_():
            nonlocal _stat
            if _stat is None:
                _stat = os.stat(path)
            return _stat

        if self.ATime is not None:
            assert stat_().st_atime_ns == self.ATime

        if self.MTime is not None:
            assert stat_().st_mtime_ns == self.MTime

        if self.User is not None:
            assert stat_().st_uid == self.User

        if self.Group is not None:
            assert stat_().st_gid == self.Group

        if self.Mode is not None:
            assert stat.S_IMODE(stat_().st_mode) == self.Mode

    def __str__(self):
        r = self._str('.', True, '')
        return r

    def _str(self, name, exists, prefix):
        r = [prefix, ('- ' if exists else '# '), name]
        r = ''.join(r)
        return r

    def __repr__(self):
        return str(self)


class RegularFile(File):
    def __init__(self, aTime=None, mTime=None, user=None, group=None, mode=None):
        super().__init__(aTime, mTime, user, group, mode)

        self._Path = None

    def create(self, path):
        if ospath.exists(path):
            raise FileExistsError(path)

        if self._Path is not None:
            os.link(self._Path, path)
            return

        with open(path, 'w'):
            pass

        self._create(path)

        self._Path = path

    def assert_(self, path):
        super().assert_(path)

        assert os.stat(path).st_size == 0


class Directory(File):
    def __init__(self,
                 existingFiles,
                 existingFilesComplete,
                 notExistingFiles,
                 aTime=None,
                 mTime=None,
                 user=None,
                 group=None,
                 mode=None):
        super().__init__(aTime, mTime, user, group, mode)

        self.ExistingFiles = existingFiles
        self.ExistingFilesComplete = existingFilesComplete
        self.NotExistingFiles = notExistingFiles

    def create(self, path):
        os.mkdir(path)

        for name, file in self.ExistingFiles.items():
            p = ospath.join(path, name)
            file.create(p)

        self._create(path)

    def assert_(self, path):
        super().assert_(path)

        for name, file in self.ExistingFiles.items():
            p = ospath.join(path, name)
            file.assert_(p)

        if self.ExistingFilesComplete:
            assert self.ExistingFiles.keys() == set(os.listdir(path))

        for name in self.NotExistingFiles.keys():
            p = ospath.join(path, name)
            assert not ospath.exists(p)

    # helper
    def __len__(self):
        return len(self.ExistingFiles)

    def __getitem__(self, name):
        return self.ExistingFiles[name]

    def __setitem__(self, name, file):
        self.NotExistingFiles.pop(name, None)

        self.ExistingFiles[name] = file

    def __delitem__(self, name):
        file = self.ExistingFiles.pop(name)

        self.NotExistingFiles[name] = file

    def pop(self, name):
        r = self.ExistingFiles[name]
        del self[name]
        return r

    #

    def __str__(self):
        r = [
            '',
            self._str('.', True, ''),
            '',
        ]
        r = '\n'.join(r)
        return r

    def _str(self, name, exists, prefix):
        r = [
            [prefix, '+ ' if exists else '# ', name],
        ]

        nPrefix = prefix + ' ' * 2
        for nName, file in sorted(self.ExistingFiles.items()):
            r.append([file._str(nName, exists, nPrefix)])

        if not self.ExistingFilesComplete:
            r.append([prefix, '  *'])

        for nName, file in sorted(self.NotExistingFiles.items()):
            r.append([file._str(nName, False, nPrefix)])

        r = '\n'.join(''.join(line) for line in r)
        return r


class Context:
    def __init__(self, directory, path):
        self.Directory = directory
        self.Path = path

    def __enter__(self):
        self.Directory.create(self.Path)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        shutil.rmtree(self.Path)


names = hys.text(alphabet=NAME_ALPHABET, min_size=1, max_size=255).filter(lambda name: name not in ['.', '..'])

times = hys.integers(min_value=-(2**64), max_value=2**64 - 1)


@hys.composite
def users(draw):
    uid = os.getuid()

    if uid == 0:  # root
        ids = get_user_ids()

        if len(ids) == 1:
            r, = ids

        else:
            r = draw(hys.sampled_from(ids))

    else:
        r = uid

    return r


users = users()


@hys.composite
def groups(draw):
    ids = get_group_ids()
    if len(ids) == 0:
        return None

    if len(ids) == 1:
        r, = ids
        return r

    r = draw(hys.sampled_from(ids))
    return r


groups = groups()


@hys.composite
def modes(draw):
    if os.getuid() == 0:  # root
        r = 0
        parts = [
            stat.S_IRUSR, stat.S_IWUSR, stat.S_IXUSR, stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP, stat.S_IROTH,
            stat.S_IWOTH, stat.S_IXOTH
        ]

    else:
        r = stat.S_IRWXU
        parts = [stat.S_IRGRP, stat.S_IWGRP, stat.S_IXGRP, stat.S_IROTH, stat.S_IWOTH, stat.S_IXOTH]

    parts = draw(subsets(parts))

    for part in parts:
        r |= part

    return r


modes = modes()


@hys.composite
def regular_files(draw, withATime=False, withMTime=False, withUser=False, withGroup=False, withMode=False):
    aTime = draw(times) if withATime else None
    mTime = draw(times) if withMTime else None
    user = draw(users) if withUser else None
    group = draw(groups) if withGroup else None
    mode = draw(modes) if withMode else None

    r = RegularFile(aTime=aTime, mTime=mTime, user=user, group=group, mode=mode)
    return r


@hys.composite
def _directories(draw, withATime, withMTime, withUser, withGroup, withMode, files):
    aTime = draw(times) if withATime else None
    mTime = draw(times) if withMTime else None
    user = draw(users) if withUser else None
    group = draw(groups) if withGroup else None
    mode = draw(modes) if withMode else None

    ff = draw(hys.dictionaries(names, hys.tuples(files, hys.booleans())))

    existingFiles = {}
    notExistingFiles = {}
    for name, (file, exists) in ff.items():
        if exists:
            existingFiles[name] = file

        else:
            notExistingFiles[name] = file

    r = Directory(existingFiles, True, notExistingFiles, aTime=aTime, mTime=mTime, user=user, group=group, mode=mode)
    return r


def files(withATime=False, withMTime=False, withUser=False, withGroup=False, withMode=False):
    def _dirs(files):
        return _directories(withATime, withMTime, withUser, withGroup, withMode, files)

    return hys.recursive(
        regular_files(
            withATime=withATime, withMTime=withMTime, withUser=withUser, withGroup=withGroup, withMode=withMode),
        _dirs)


@hys.composite
def directories(draw, withATime=False, withMTime=False, withUser=False, withGroup=False, withMode=False):
    def _dirs(files):
        return _directories(withATime, withMTime, withUser, withGroup, withMode, files)

    r = draw(
        _dirs(
            hys.recursive(
                regular_files(
                    withATime=withATime,
                    withMTime=withMTime,
                    withUser=withUser,
                    withGroup=withGroup,
                    withMode=withMode) | hys.just(_HardLink), _dirs)))

    links = []
    files = []

    _directories_collect('', r, links, files)

    if len(links) == 0:
        return r

    if len(files) == 0:
        file = draw(
            regular_files(
                withATime=withATime, withMTime=withMTime, withUser=withUser, withGroup=withGroup, withMode=withMode))
        files.append((None, file))

    if len(files) == 1:
        file, = files
        links = [(link, file) for link in links]

    else:
        links.sort()
        files.sort()

        files = draw(hys.lists(hys.sampled_from(files), min_size=len(links), max_size=len(links)))

        links = ((link, file) for link, file in zip(links, files))

    for link, file in links:
        _, name, collection = link
        _, file = file

        collection[name] = file

    return r


def _directories_collect(path, directory, rLinks, rFiles):
    for collection in [directory.ExistingFiles, directory.NotExistingFiles]:
        for name, file in collection.items():
            p = ospath.join(path, name)

            if isinstance(file, RegularFile):
                rFiles.append((p, file))

            elif file is _HardLink:
                rLinks.append((p, name, collection))

            elif isinstance(file, Directory):
                _directories_collect(p, file, rLinks, rFiles)


class _HardLink:
    pass


@hys.composite
def choose(draw, directory):
    files = []
    _choose_collect('', directory, True, files)

    if len(files) == 0:
        path = file = exists = None

    elif len(files) == 1:
        (path, file, exists), = files

    else:
        files.sort()
        path, file, exists = draw(hys.sampled_from(files))

    r = path, file, exists
    return r


def _choose_collect(path, directory, exists, r):
    for name, f in directory.ExistingFiles.items():
        p = ospath.join(path, name)
        r.append((p, f, exists))
        if isinstance(f, Directory):
            _choose_collect(p, f, exists, r)

    for name, f in directory.NotExistingFiles.items():
        p = ospath.join(path, name)
        r.append((p, f, False))
        if isinstance(f, Directory):
            _choose_collect(p, f, False, r)


if False:
    with Context(
            directories(withATime=True, withMTime=True, withUser=True, withGroup=True, withMode=True).example(),
            './test') as context:
        print(context.Directory)
        input('exit?')
