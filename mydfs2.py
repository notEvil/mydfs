import fuse
import os
import logging
import threading
import stat

ospath = os.path


def oserror(f):
    def translate_oserror(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except OSError as e:
            raise fuse.FuseOSError(e.errno)
    return translate_oserror


class Mydfs2(fuse.LoggingMixIn, fuse.Operations):
    def __init__(self, roots):
        self.Roots = roots  # [(c, root)]

        self._Roots = [(c, ospath.realpath(root)) for c, root in roots]
        self._OpenFhs = {}  # {fh: [fh]}
        # see self._getFhLock
        self._FhLock = threading.Lock()
        self._FhLocks = {}  # {fh: Lock}

    # def __call__(self, op, *args):

    @oserror
    def access(self, path, amode):
        for _, sPath in self._resolve(path):
            if not os.access(sPath, amode):
                raise fuse.FuseOSError(fuse.EACCES)

    @oserror
    def chmod(self, path, mode):
        for _, sPath in reversed(self._resolve(path)):
            r = os.chmod(sPath, mode)
        return r

    @oserror
    def chown(self, path, uid, gid):
        for _, sPath in reversed(self._resolve(path)):
            r = os.chown(sPath, uid, gid)
        return r

    @oserror
    def create(self, path, mode, fi=None):
        fhs = []
        try:
            for _, sPath in reversed(self._resolve(path, orBestNe=True)):
                self._ensureDir(sPath)
                fh = os.open(sPath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
                fhs.append(fh)
        except:
            for fh in reversed(fhs):
                os.close(fh)
            raise

        r = fhs[-1]
        self._OpenFhs[r] = fhs
        return r

    # def destroy(self, path):

    @oserror
    def flush(self, path, fh):
        for fh in self._OpenFhs[fh]:
            r = os.fsync(fh)
        return r

    @oserror
    def fsync(self, path, datasync, fh):
        sync = os.fdatasync if datasync != 0 else os.fsync
        for fh in self._OpenFhs[fh]:
            r = sync(fh)
        return r

    # def fsyncdir(self, path, datasync, fh):

    @oserror
    def getattr(self, path, fh=None):
        # used for exists -> need to lstat all
        # TODO might be relaxed for performance improvement
        for _, sPath in reversed(self._resolve(path)):
            st = os.lstat(sPath)

        return {key: getattr(st, key) for key in ('st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime', 'st_nlink',
                                                  'st_size', 'st_uid')}

    getxattr = None  # TODO could be a useful feature to add

    # def init(self, path):

    @oserror
    def link(self, target, source):
        '''
        - hard link
        - target without source -> file not found error
        - target exists -> file exists error
        - source without target -> ignored
        '''
        sources = dict(self._resolve(source))

        try:
            targets = self._resolve(target)
        except fuse.FuseOSError:  # targets not specified or don't exist
            targets = {root: root + target for root in sources}
        else:
            targets = dict(targets)
        # len(targets) != 0

        if len(targets.keys() - sources.keys()) != 0:
            raise fuse.FuseOSError(fuse.ENOENT)
        # targets is subset of sources

        for _, path in targets:
            if ospath.exists(path):
                raise fuse.FuseOSError(fuse.EEXIST)
        # no target exists

        for root, targetPath in targets.items():
            self._ensureDir(targetPath)
            r = os.link(sources[root], targetPath)
        # random order!

        return r

        if False:
            '''
            wrong but probably useful in the future
            '''
            sources = dict(self._resolve(source))
            targets = dict(self._resolve(target, orBestNe=True))
            # targets either exist
            # or len() == 1

            # potential overwrite
            for root in sources.keys() & targets.keys():
                r = os.link(sources[root], targets[root])

            # create same root
            roots = sources.keys() - targets.keys()
            if len(roots) != 0:
                root, t = next(iter(targets.items()))
                t = t[len(root):]

                for root in roots:
                    path = root + t
                    os.makedirs(ospath.dirname(path), exist_ok=True)
                    r = os.link(sources[root], path)

            # delete different root
            for root in targets.keys() - sources.keys():
                os.unlink(targets[root])

            return r

    listxattr = None  # TODO see getxattr

    @oserror
    def mkdir(self, path, mode):
        for _, sPath in reversed(self._resolve(path, orBestNe=True)):
            self._ensureDir(sPath)
            r = os.mkdir(sPath, mode)
        return r

    @oserror
    def mknod(self, path, mode, dev):
        for _, sPath in reversed(self._resolve(path), orBestNe=True):
            self._ensureDir(sPath)
            r = os.mknod(sPath, mode, dev)
        return r

    @oserror
    def open(self, path, flags):
        paths = reversed(self._resolve(path, orBestNe=True))
        fhs = []
        try:
            for _, sPath in paths:
                fh = os.open(sPath, flags)
                fhs.append(fh)
        except:
            for fh in reversed(fhs):
                os.close(fh)
            raise

        r = fhs[-1]
        self._OpenFhs[r] = fhs
        return r

    # def opendir(self, path):

    @oserror
    def read(self, path, size, offset, fh):
        with self._getFhLock(fh):
            os.lseek(fh, offset, 0)
            r = os.read(fh, size)

            # TODO could be very wrong
            nOffset = os.lseek(fh, 0, os.SEEK_CUR)
            for fhi in self._OpenFhs[fh]:
                os.lseek(fhi, nOffset, 0)
        return r

    @oserror
    def readdir(self, path, fh):
        # TODO check performance

        r = set()
        allObjs = set()
        objss = []

        for _, root in self._Roots:
            base = root + path
            try:
                names = os.listdir(base)
            except FileNotFoundError:
                names = []

            objs = set()
            for name in names:
                st = os.lstat(ospath.join(base, name))

                if stat.S_ISDIR(st.st_mode):
                    r.add(name)
                    continue

                objs.add((name, st.st_mtime, st.st_size))

            allObjs |= objs
            objss.append(objs)

        r = list(r)

        for obj in allObjs:
            mask = ''.join(c if obj in objs else '.'
                           for (c, _), objs in zip(self._Roots, objss))
            r.append('_'.join([mask, obj[0]]))

        return r

        if False:
            allNames = set()
            namess = []

            for _, root in self._Roots:
                base = root + path
                try:
                    names = os.listdir(base)
                except FileNotFoundError:
                    namess.append(set())
                    continue

                names = set(names)
                allNames |= names
                namess.append(names)

            r = []
            for name in allNames:
                mask = ''.join(c if name in names else '.'
                               for (c, _), names in zip(self._Roots, namess))
                r.append('_'.join([mask, name]))

            return r

    @oserror
    def readlink(self, path):
        return os.readlink(self._resolve(path)[0][1])

    @oserror
    def release(self, path, fh):
        for fh in self._OpenFhs.pop(fh):
            r = os.close(fh)
        return r

    # def releasedir(self, path, fh):

    # def removexattr(self, path, name): # TODO see getxattr

    @oserror
    def rename(self, old, new):
        '''
        - like self.link
        - new without old -> file not found error
        - rename for existing new first
        - old without new -> ignored
        '''

        olds = dict(self._resolve(old))
        try:
            news = self._resolve(new)
        except fuse.FuseOSError:
            news = {root: root + new for root in olds}
        else:
            news = dict(news)
        # len(news) != 0

        if len(news.keys() - olds.keys()) != 0:
            raise fuse.FuseOSError(fuse.ENOENT)
        # news is subset of olds

        news = sorted(news.items(), key=lambda item: ospath.exists(item[1]), reverse=True)
        # existing new are first
        for root, newPath in news:
            self._ensureDir(newPath)
            r = os.rename(olds[root], newPath)

        return r

    @oserror
    def rmdir(self, path):
        for _, sPath in reversed(self._resolve(path)):
            r = os.rmdir(sPath)
        return r

    # def setxattr(self, path, name, value, options, position=0): TODO see getxattr

    @oserror
    def statfs(self, path):
        stv = os.statvfs(self._resolve(path)[0][1])
        return {key: getattr(stv, key) for key in ('f_bavail', 'f_bfree', 'f_blocks', 'f_bsize', 'f_favail', 'f_ffree',
                                                   'f_files', 'f_flag', 'f_frsize', 'f_namemax')}

    @oserror
    def symlink(self, target, source):
        '''
        - like self.link
        '''
        sources = dict(self._resolve(source))

        try:
            targets = self._resolve(target)
        except fuse.FuseOSError:
            targets = {root: root + target for root in sources}
        else:
            targets = dict(targets)
        # len(targets) != 0

        if len(targets.keys() - sources.keys()) != 0:
            raise fuse.FuseOSError(fuse.ENOENT)
        # targets is subset of sources

        for _, path in targets:
            if ospath.exists(path):
                raise fuse.FuseOSError(fuse.EEXIST)
        # no target exists

        for root, targetPath in targets.items():
            self._ensureDir(targetPath)
            r = os.symlink(sources[root], targetPath)
        # random order!

        return r

    @oserror
    def truncate(self, path, length, fh=None):
        for _, sPath in reversed(self._resolve(path)):
            with open(sPath, 'r+') as f:
                r = f.truncate(length)
        return r

    @oserror
    def unlink(self, path):
        for _, sPath in reversed(self._resolve(path)):
            r = os.unlink(sPath)
        return r

    @oserror
    def utimens(self, path, times=None):
        for _, sPath in reversed(self._resolve(path)):
            r = os.utime(sPath, times=times)
        return r

    @oserror
    def write(self, path, data, offset, fh):
        with self._getFhLock(fh):
            for fhi in self._OpenFhs[fh]:
                os.lseek(fhi, offset, 0)
                r = os.write(fhi, data)
        return r

    def _resolve(self, path, orBestNe=False):
        r = []

        dirPath, name = ospath.split(path)

        n = len(self._Roots)
        if n < len(name) and name[n] == '_':
            realPath = ospath.join(dirPath, name[(n + 1):])

            for nC, (sC, root) in zip(name, self._Roots):
                if nC == '.':
                    continue
                if nC != sC:
                    break
                r.append((root, root + realPath))
            else:
                if len(r) != 0:
                    return r

        r.clear()
        for _, root in self._Roots:
            n = root + path
            if ospath.exists(n):
                r.append((root, n))

        if len(r) != 0:
            return r
        if orBestNe:
            return [self._best_ne(path)]

        raise fuse.FuseOSError(fuse.ENOENT)

    def _best_ne(self, path):
        # get all names
        names = []
        p = path
        while p != '/':
            p, name = ospath.split(p)
            names.append(name)

        # find longest matching paths
        names = iter(reversed(names))
        r = [(root, root) for _, root in self._Roots]
        for name in names:
            r = [(root, ospath.join(path, name)) for root, path in r]
            nR = [ri for ri in r if ospath.exists(ri[1])]
            if len(nR) == 0:
                break
            r = nR

        root, path = r[0]
        for name in names:
            path = ospath.join(path, name)

        return root, path

    def _getFhLock(self, fh):
        with self._FhLock:
            r = self._FhLocks.get(fh, None)
            if r is None:
                self._FhLocks[fh] = r = threading.Lock()
        return r

    def _ensureDir(self, path):
        os.makedirs(ospath.dirname(path), exist_ok=True)


if __name__ == '__main__':
    import sys

    def printUsage():
        print('usage: {} [--debug] <c>=<root> [<c>=<root> ...] <mountpoint>'.format(sys.argv[0]))

    args = sys.argv[1:]

    if '--debug' in args:
        debug = True
        args.remove('--debug')
    else:
        debug = False

    if len(args) < 2:
        print('too few arguments')
        printUsage()
        exit(1)

    rootArgs = args[:-1]
    roots = []
    for i, arg in enumerate(rootArgs):
        if len(arg) < 3 or arg[1] != '=':
            print('invalid argument {}'.format(repr(arg)))
            printUsage()
            exit(2)

        root = arg[2:]
        if not ospath.isdir(root):
            print('root either does not exist or is not a directory {}'.format(repr(root)))
            exit(3)

        roots.append((arg[0], root))

    mountpoint = args[-1]

    logging.basicConfig()

    fuse.FUSE(Mydfs2(roots), mountpoint, foreground=True, debug=debug)
