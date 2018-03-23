'''
TODO
'''

# TODO
import fuse
import os
import logging
import threading
import stat
import boltons.funcutils

ospath = os.path


def fuse_errors(f):
    '''
    Decorator to replace `OSError` by `fuse.FuseOSError`.

    @param f function
    @return function
    '''

    @boltons.funcutils.wraps(f)
    def _fuse_errors(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except OSError as e:
            raise fuse.FuseOSError(e.errno) from e

    return _fuse_errors


class Mydfs(fuse.LoggingMixIn, fuse.Operations):
    '''
    Main class for use with `fuse.FUSE`.
    '''

    def __init__(self, roots):
        '''
        @param roots iter((str, str)); sequence of (character, path to root)
        '''
        self.Roots = roots

        _roots = []
        for c, root in roots:
            if len(c) != 1:
                raise ValueError('zero or more than one character for root {}: {}'.format(repr(root), repr(c)))

            _roots.append((c, ospath.realpath(root)))

        self._Roots = _roots  # {character: real path}
        self._OpenFileHandles = {}  # {file handle: [file handle]}

        # see self._get_file_handle_lock
        self._FileHandleLock = threading.Lock()
        self._FileHandleLocks = {}  # {file handle: Lock}

    # def __call__(self, op, *args):  # residual from fusepy loopback example

    @fuse_errors
    def access(self, path, amode):
        for _, p in self._resolve(path):
            if not os.access(p, amode):
                raise fuse.FuseOSError(fuse.EACCES)

    @fuse_errors
    def chmod(self, path, mode):
        for _, p in reversed(self._resolve(path)):
            r = os.chmod(p, mode)

        return r

    @fuse_errors
    def chown(self, path, uid, gid):
        for _, p in reversed(self._resolve(path)):
            r = os.chown(p, uid, gid)

        return r

    @fuse_errors
    def create(self, path, mode, fi=None):
        fileHandles = []
        try:
            for _, p in reversed(self._resolve(path, orBestInexistent=True)):
                self._ensure_directory(p)
                fileHandle = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
                fileHandles.append(fileHandle)

        except Exception:
            for fileHandle in reversed(fileHandles):
                os.close(fileHandle)

            raise

        r = fileHandles[-1]
        self._OpenFileHandles[r] = fileHandles
        return r

    # def destroy(self, path):  # residual from FUSE doc

    @fuse_errors
    def flush(self, path, fileHandle):
        for fileHandle in self._OpenFileHandles[fileHandle]:
            r = os.fsync(fileHandle)

        return r

    @fuse_errors
    def fsync(self, path, datasync, fileHandle):
        sync = os.fdatasync if datasync != 0 else os.fsync  # from fusepy loopback example
        for fileHandle in self._OpenFileHandles[fileHandle]:
            r = sync(fileHandle)

        return r

    # def fsyncdir(self, path, datasync, fh):  # residual from FUSE doc

    @fuse_errors
    def getattr(self, path, fh=None):
        '''
        This function is used to test for existence.
        Therefore `os.lstat` is called for all paths.
        This might not be necessary.
        '''
        for _, p in reversed(self._resolve(path)):
            stat = os.lstat(p)

        return {
            key: getattr(stat, key)
            for key in ('st_mode', 'st_ino', 'st_dev', 'st_nlink', 'st_uid', 'st_gid', 'st_size', 'st_atime',
                        'st_mtime', 'st_ctime', 'st_atime_ns', 'st_mtime_ns', 'st_ctime_ns')
        }

    getxattr = None  # TODO could be a useful feature to add

    # TODO stopped here

    @fuse_errors
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
            self._ensure_directory(targetPath)
            r = os.link(sources[root], targetPath)
        # random order!

        return r

        if False:
            '''
            wrong but probably useful in the future
            '''
            sources = dict(self._resolve(source))
            targets = dict(self._resolve(target, orBestInexistent=True))
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

    @fuse_errors
    def mkdir(self, path, mode):
        for _, sPath in reversed(self._resolve(path, orBestInexistent=True)):
            self._ensure_directory(sPath)
            r = os.mkdir(sPath, mode)
        return r

    @fuse_errors
    def mknod(self, path, mode, dev):
        for _, sPath in reversed(self._resolve(path), orBestInexistent=True):
            self._ensure_directory(sPath)
            r = os.mknod(sPath, mode, dev)
        return r

    @fuse_errors
    def open(self, path, flags):
        paths = reversed(self._resolve(path, orBestInexistent=True))
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
        self._OpenFileHandles[r] = fhs
        return r

    # def opendir(self, path):

    @fuse_errors
    def read(self, path, size, offset, fh):
        with self._get_file_handle_lock(fh):
            os.lseek(fh, offset, 0)
            r = os.read(fh, size)

            # TODO could be very wrong
            nOffset = os.lseek(fh, 0, os.SEEK_CUR)
            for fhi in self._OpenFileHandles[fh]:
                os.lseek(fhi, nOffset, 0)
        return r

    @fuse_errors
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
            mask = ''.join(c if obj in objs else '.' for (c, _), objs in zip(self._Roots, objss))
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
                mask = ''.join(c if name in names else '.' for (c, _), names in zip(self._Roots, namess))
                r.append('_'.join([mask, name]))

            return r

    @fuse_errors
    def readlink(self, path):
        return os.readlink(self._resolve(path)[0][1])

    @fuse_errors
    def release(self, path, fh):
        for fh in self._OpenFileHandles.pop(fh):
            r = os.close(fh)
        return r

    # def releasedir(self, path, fh):

    # def removexattr(self, path, name): # TODO see getxattr

    @fuse_errors
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
            self._ensure_directory(newPath)
            r = os.rename(olds[root], newPath)

        return r

    @fuse_errors
    def rmdir(self, path):
        for _, sPath in reversed(self._resolve(path)):
            r = os.rmdir(sPath)
        return r

    # def setxattr(self, path, name, value, options, position=0): TODO see getxattr

    @fuse_errors
    def statfs(self, path):
        stv = os.statvfs(self._resolve(path)[0][1])
        return {
            key: getattr(stv, key)
            for key in ('f_bavail', 'f_bfree', 'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
                        'f_frsize', 'f_namemax')
        }

    @fuse_errors
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
            self._ensure_directory(targetPath)
            r = os.symlink(sources[root], targetPath)
        # random order!

        return r

    @fuse_errors
    def truncate(self, path, length, fh=None):
        for _, sPath in reversed(self._resolve(path)):
            with open(sPath, 'r+') as f:
                r = f.truncate(length)
        return r

    @fuse_errors
    def unlink(self, path):
        for _, sPath in reversed(self._resolve(path)):
            r = os.unlink(sPath)
        return r

    @fuse_errors
    def utimens(self, path, times=None):
        for _, sPath in reversed(self._resolve(path)):
            r = os.utime(sPath, times=times)
        return r

    @fuse_errors
    def write(self, path, data, offset, fh):
        with self._get_file_handle_lock(fh):
            for fhi in self._OpenFileHandles[fh]:
                os.lseek(fhi, offset, 0)
                r = os.write(fhi, data)
        return r

    def _resolve(self, path, orBestInexistent=False):
        '''
        - if base name contains valid mask
          - returns corresponding paths
        - tests all paths for existence
        - if any
          - returns paths
        - if `orBestInexistent`
          - returns best inexistent path
        - raises not found error

        Warning:
        - assumes
          - `path` is absolute path. TODO check
        '''

        r = []

        dirPath, name = ospath.split(path)

        nRoots = len(self._Roots)
        if nRoots < len(name) and name[nRoots] == '_':  # could contain mask
            realPath = ospath.join(dirPath, name[(nRoots + 1):])

            for maskCharacter, (rootCharacter, root) in zip(name, self._Roots):
                if maskCharacter == '.':  # not there
                    continue
                if maskCharacter != rootCharacter:  # invalid mask
                    break

                r.append((root, root + realPath))

            else:
                if len(r) != 0:  # valid mask
                    return r

        # test all paths for existence
        r.clear()
        for _, root in self._Roots:
            p = root + path
            if ospath.exists(p):
                r.append((root, p))

        if len(r) != 0:  # found any
            return r

        if orBestInexistent:
            r.append(self._get_best_inexistent(path))
            return r

        raise fuse.FuseOSError(fuse.ENOENT)

    def _get_best_inexistent(self, path):
        # find paths which match longest
        names = path.split('/')

        iNames = iter(names)
        paths = [(root, root) for _, root in self._Roots]
        for name in iNames:
            paths = [(root, ospath.join(path, name)) for root, path in paths]
            nPaths = [pair for pair in paths if ospath.exists(pair[1])]

            if len(nPaths) == 0:
                break

            paths = nPaths

        # complete path
        root, path = paths[0]
        path = ospath.join(path, *iNames)

        return (root, path)

    def _get_file_handle_lock(self, fh):
        with self._FileHandleLock:
            r = self._FileHandleLocks.get(fh, None)
            if r is None:
                self._FileHandleLocks[fh] = r = threading.Lock()
        return r

    def _ensure_directory(self, path):
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

    fuse.FUSE(Mydfs(roots), mountpoint, foreground=True, debug=debug)
