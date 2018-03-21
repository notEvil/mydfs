import fuse
import os
import logging
import threading

pathexists = os.path.exists
pathsplit = os.path.split
pathjoin = os.path.join


def forall1(f):
    def forall1(mydfs, path, *args, **kwargs):
        return [f(mydfs, p, *args, **kwargs) for root, p in mydfs._all(path)]
    return forall1

def forfirst1(f):
    def forfirst1(mydfs, path, *args, **kwargs):
        return f(mydfs, mydfs._first(path)[1], *args, **kwargs)
    return forfirst1

def forbestne1(f):
    def forbestne1(mydfs, path, *args, **kwargs):
        return f(mydfs, mydfs._best_ne(path)[1], *args, **kwargs)
    return forbestne1


def first(f):
    def first(*args, **kwargs):
        return f(*args, **kwargs)[0]
    return first

def opens(f):
    def opens(mydfs, *args, **kwargs):
        handles = f(mydfs, *args, **kwargs)
        r = handles[0]
        mydfs.OpenHandles[r] = handles
        return r
    return opens

class handles:
    def __init__(self, i):
        self.I = i

    def __call__(self, f):
        def handles(mydfs, *args, **kwargs):
            args = list(args)
            r = []
            for handle in mydfs.OpenHandles[args[self.I]]:
                args[self.I] = handle
                r.append(f(mydfs, *args, **kwargs))
            return r
        return handles


class Mydfs(fuse.LoggingMixIn, fuse.Operations):
    '''
    - Mydfs = my distributed file system
    - "merges" multiple folders (roots)
    - access
      - granted if for all
    - rename/link
      - within root !
      - order
        - rename/link to sources with existing targets
        - rename/link to sources without existing targets
          - folders are created as necessary
        - remove targets without sources
        - rename/link to not existing sources with existing targets
        - rename/link to not existing sources with non existing targets
    - operations on all existing or closest
      - chmod
      - chown
      - create
      - flush
      - fsync
      - open
      - read
        - reads first only
        - seeks others
      - readdir
      - release
      - rmdir
      - truncate
      - unlink
      - write
    - operations on first existing or closest
      - getattr
      - readlink
      - statfs
      - utimens
    - operations on closest
      - mkdir
      - mknod
      - symlink
    - copy
      - usually with existing source and not existing target
      - blockwise read from first existing file
      - between roots if closest is on different root
    '''

    def __init__(self, roots):
        self.Roots = [os.path.realpath(root) for root in roots]

        self.OpenHandles = {} # TODO need all files open?
        self.RwLock = threading.Lock()
        self.HandleLocks = {}

    # def __call__(self, op, *args):

    @first
    @forall1
    def access(self, path, amode):
        if not os.access(path, amode):
            raise fuse.FuseOSError(fuse.EACCES)

    @first
    @forall1
    def chmod(self, path, mode):
        return os.chmod(path, mode)

    @first
    @forall1
    def chown(self, path, uid, gid):
        return os.chown(path, uid, gid)

    @opens
    @forall1
    def create(self, path, mode, fi=None):
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

    # def destroy(self, path):

    @first
    @handles(1)
    def flush(self, path, fh):
        return os.fsync(fh)

    @first
    @handles(2)
    def fsync(self, path, datasync, fh):
        if datasync != 0:
            return os.fdatasync(fh)
        else:
            return os.fsync(fh)

    # def fsyncdir(self, path, datasync, fh):

    @forfirst1
    def getattr(self, path, fh=None):
        st = os.lstat(path)
        return {key: getattr(st, key) for key in ('st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid')}

    getxattr = None # TODO could be a useful feature to add

    # def init(self, path):

    def link(self, target, source):
        '''
        see rename
        '''
        sources = dict(self._all_e(source))
        targets = dict(self._all_e(target))

        if len(sources) != 0:
            for root in sources.keys() & targets.keys(): # overwrite
                r = os.link(sources[root], targets[root])
            for root in sources.keys() - targets.keys(): # create same root
                path = root + target
                os.makedirs(os.path.dirname(path), exist_ok=True)
                r = os.link(sources[root], path)
            for root in targets.keys() - sources.keys(): # delete different root
                os.unlink(targets[root])

        elif len(targets) != 0:
            for root, path in targets.items():
                r = os.link(root + source, path)

        else:
            r = os.link(self._best_ne(source)[1], self._best_ne(target)[1])

        return r


    listxattr = None # TODO see getxattr

    @forbestne1
    def mkdir(self, path, mode):
        return os.mkdir(path, mode)

    @forbestne1
    def mknod(self, path, mode, dev):
        return os.mknod(path, mode, dev)

    @opens
    @forall1
    def open(self, path, flags):
        return os.open(path, flags)

    # def opendir(self, path):

    def read(self, path, size, offset, fh):
        with self._getHandleLock(fh):
            os.lseek(fh, offset, 0)
            r = os.read(fh, size)

            # TODO could be very wrong
            nOffset = os.lseek(fh, 0, os.SEEK_CUR)
            for fhi in self.OpenHandles[fh]:
                os.lseek(fhi, nOffset, 0)
        return r

    def readdir(self, path, fh):
        seen = set()
        r = ['.', '..']
        for root, path in self._all_e(path):
            for name in os.listdir(path):
                if name in seen:
                    continue
                seen.add(name)
                r.append(name)
        return r

    @forfirst1
    def readlink(self, path):
        return os.readlink(path)

    def release(self, path, fh):
        r = []
        for fh in self.OpenHandles.pop(fh):
            r.append(os.close(fh))
        return r[0]

    # def releasedir(self, path, fh):

    # def removexattr(self, path, name): # TODO see getxattr

    def rename(self, old, new):
        '''
        - old exist, new exist
          - rename old to new on same root
            - rename old to existing new
            - rename old to not existing new
          - remove new with not existing old
        - old exist, new not exist
          - rename old to new on same root
          - special case of (old exist, new exist)
        - old not exist, new exist
          - rename old with existing new to existing new
        - old not exist, new not exist
          - rename best old to best new
        '''

        olds = dict(self._all_e(old))
        news = dict(self._all_e(new))

        if len(olds) != 0:
            # TODO failure could leave fs in inconsistent state
            for root in olds.keys() & news.keys(): # overwrite
                r = os.rename(olds[root], news[root])

            # n = olds.keys() - news.keys()
            # if len(n) != 0:
                # bestNew = self._best_ne(new)[1]
            # for root in n:
                # r = os.rename(olds[root], bestNew)
            for root in olds.keys() - news.keys(): # move same root
                path = root + new
                os.makedirs(os.path.dirname(path), exist_ok=True)
                r = os.rename(olds[root], path)

            for root in news.keys() - olds.keys(): # delete different root
                os.unlink(news[root])

        elif len(news) != 0:
            for root, path in news.items():
                r = os.rename(root + old, path)

        else:
            r = os.rename(self._best_ne(old)[1], self._best_ne(new)[1])

        return r


    @first
    @forall1
    def rmdir(self, path):
        return os.rmdir(path)

    # def setxattr(self, path, name, value, options, position=0): TODO see getxattr

    @forfirst1
    def statfs(self, path):
        stv = os.statvfs(path)
        return {key: getattr(stv, key) for key in ('f_bavail', 'f_bfree', 'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag', 'f_frsize', 'f_namemax')}

    @forbestne1
    def symlink(self, target, source):
        return os.symlink(source, target)

    @first
    @forall1
    def truncate(self, path, length, fh=None):
        with open(path, 'r+') as f:
            f.truncate(length)

    @first
    @forall1
    def unlink(self, path):
        return os.unlink(path)

    @forfirst1
    def utimens(self, path, times=None):
        return os.utime(path, times=times)

    def write(self, path, data, offset, fh):
        with self._getHandleLock(fh):
            for fhi in self.OpenHandles[fh]:
                os.lseek(fhi, offset, 0)
                r = os.write(fhi, data)
        return r


    def _all_e(self, path):
        r = []
        for root in self.Roots:
            p = root + path
            if not pathexists(p):
                continue
            r.append((root, p))
        return r

    def _all(self, path):
        r = self._all_e(path)
        if len(r) == 0:
            return [self._best_ne(path)]
        return r

    # def _all2(self, path1, path2):
        # r = []
        # for root in self.Roots:
            # rPath1 = root + path1
            # if not pathexists(rPath1):
                # continue
            # r.append((rPath1, root + path2))
        # if len(r) == 0:
            # return [(self._best_ne(path1), self._best_ne(path2))]
        # return r

    def _first_e(self, path):
        for root in self.Roots:
            r = root + path
            if pathexists(r):
                return root, r
        return None

    def _first(self, path):
        r = self._first_e(path)
        if r is None:
            return self._best_ne(path)
        return r

    def _best_ne(self, path):
        # get all names
        names = []
        p = path
        while p != '/':
            p, name = pathsplit(p)
            names.append(name)

        # find longest matching paths
        names = iter(reversed(names))
        r = [(root, root) for root in self.Roots]
        for name in names:
            r = [(root, pathjoin(path, name)) for root, path in r]
            nR = [ri for ri in r if pathexists(ri[1])]
            if len(nR) == 0:
                break
            r = nR

        root, r = r[0]
        for name in names:
            r = pathjoin(r, name)

        return root, r

    def _getHandleLock(self, fh):
        with self.RwLock:
            r = self.HandleLocks.get(fh, None)
            if r is None:
                self.HandleLocks[fh] = r = threading.Lock()
        return r


if __name__ == '__main__':
    import sys

    args = sys.argv[1:]
    if len(args) < 2:
        print('usage: {} [--debug] <root> [<root> ...] <mountpoint>'.format(sys.argv[0]))
        exit(1)

    debug = False
    roots = []
    for arg in args[:-1]:
        if arg == '--debug':
            debug = True
            continue
        roots.append(arg)

    mountpoint = args[-1]

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)

    # fuse.FUSE.OPTIONS = fuse.FUSE.OPTIONS + (('allow_other', '-o allow_other'),)
    fuse.FUSE(Mydfs(roots), mountpoint, foreground=True, allow_other=True)
