'''
TODO
'''

import fuse
import boltons.funcutils
import os
import stat
import threading
import collections

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
        '''
        Creates and opens file.

        - for all paths
          - creates parent directories as needed
          - creates and opens file
        - if any error
          - for all files opened in reversed order
            - closes file
          - raises error
        '''
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
            stat_ = os.lstat(p)

        return {
            key: getattr(stat_, key)
            for key in ('st_mode', 'st_ino', 'st_dev', 'st_nlink', 'st_uid', 'st_gid', 'st_size', 'st_atime',
                        'st_mtime', 'st_ctime', 'st_atime_ns', 'st_mtime_ns', 'st_ctime_ns')
        }

    getxattr = None  # TODO could be a useful feature to add

    # TODO stopped here

    @fuse_errors
    def link(self, target, source):
        '''
        Creates hard link.

        For details see `._link`.
        '''
        return self._link(target, source, os.link)

    listxattr = None  # TODO see getxattr

    @fuse_errors
    def mkdir(self, path, mode):
        '''
        Creates directory.

        - for all paths
          - creates parent directories as needed
          - creates directory
        '''
        for _, p in reversed(self._resolve(path, orBestInexistent=True)):
            self._ensure_directory(p)
            r = os.mkdir(p, mode)

        return r

    @fuse_errors
    def mknod(self, path, mode, dev):
        for _, p in reversed(self._resolve(path), orBestInexistent=True):
            self._ensure_directory(p)
            r = os.mknod(p, mode, dev)

        return r

    @fuse_errors
    def open(self, path, flags):
        '''
        Opens file.

        - for all paths
          - opens file
        - if error
          - for all files opened in reverse order
            - closes file
          - raises error
        '''

        fileHandles = []
        try:
            for _, p in reversed(self._resolve(path, orBestInexistent=True)):
                fileHandle = os.open(p, flags)
                fileHandles.append(fileHandle)

        except Exception:
            for fileHandle in reversed(fileHandles):
                os.close(fileHandle)

            raise

        r = fileHandles[-1]
        self._OpenFileHandles[r] = fileHandles
        return r

    # def opendir(self, path):  # residual from FUSE doc

    @fuse_errors
    def read(self, path, size, offset, fileHandle):
        '''
        Read from file.

        - acquires lock
        - sets position in file
        - reads from file
        - gets position in file
        - for all files opened
          - sets position in file
        '''

        with self._get_file_handle_lock(fileHandle):
            os.lseek(fileHandle, offset, 0)  # from fusepy loopback example
            r = os.read(fileHandle, size)

            # TODO could be very wrong
            nOffset = os.lseek(fileHandle, 0, os.SEEK_CUR)
            for nFileHandle in self._OpenFileHandles[fileHandle]:
                os.lseek(nFileHandle, nOffset, 0)

        return r

    @fuse_errors
    def readdir(self, path, fh):
        '''
        List directory.

        - for all directories
          - lists directory
          - for all names
            - if is directory
              - adds name to result
            - else
              - remembers file id
        - for all file ids
          - builds mask
          - builds and adds name to result

        file id = (name, modification time, size)
        '''

        # TODO check performance

        r = set()
        fileIds = []
        allFileIds = set()

        for _, root in self._Roots:
            p = root + path

            try:
                names = os.listdir(p)

            except FileNotFoundError:
                names = []

            fIds = set()
            for name in names:
                stat_ = os.lstat(ospath.join(p, name))

                if stat.S_ISDIR(stat_.st_mode):
                    r.add(name)
                    continue

                fIds.add((name, stat_.st_mtime_ns, stat_.st_size))

            fileIds.append(fIds)
            allFileIds.update(fIds)

        r = list(r)

        for fileId in allFileIds:
            name, _, _ = fileId

            mask = ''.join(character if fileId in fIds else '.' for (character, _), fIds in zip(self._Roots, fileIds))
            name = ''.join([mask, '_', name])
            r.append(name)

        return r

    @fuse_errors
    def readlink(self, path):
        paths = self._resolve(path)
        _, p = paths[0]
        return os.readlink(p)

    @fuse_errors
    def release(self, path, fileHandle):
        for fh in self._OpenFileHandles[fileHandle]:
            r = os.close(fh)

        del self._OpenFileHandles[fileHandle]

        return r

    # def releasedir(self, path, fh):  # residual from FUSE doc

    removexattr = None  # TODO see getxattr

    @fuse_errors
    def rename(self, old, new):
        '''
        Rename file.

        Similar to `.link`.

        - if new without old
          - raises file not found error
        - for all news
          - creates parent directories as needed
          - rename corresponding old to new
        '''
        olds = collections.OrderedDict(self._resolve(old))

        try:
            news = self._resolve(new)

        except fuse.FuseOSError:  # news not specified and don't exist
            news = ((root, root + new) for root in olds)

        news = collections.OrderedDict(news)

        # len(news) != 0

        if len(news.keys() - olds.keys()) != 0:  # new without old
            raise fuse.FuseOSError(fuse.ENOENT)

        # news is subset of olds

        for root, newPath in reversed(news.items()):
            self._ensure_directory(newPath)
            r = os.rename(olds[root], newPath)

        return r

    @fuse_errors
    def rmdir(self, path):
        for _, p in reversed(self._resolve(path)):
            r = os.rmdir(p)

        return r

    setxattr = None  # TODO see getxattr

    @fuse_errors
    def statfs(self, path):
        paths = self._resolve(path, orBestInexistent=True)
        _, p = paths[0]
        stat_ = os.statvfs(p)  # from fusepy loopback example

        return {
            key: getattr(stat_, key)
            for key in ('f_bavail', 'f_bfree', 'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
                        'f_frsize', 'f_namemax')
        }

    @fuse_errors
    def symlink(self, target, source):
        '''
        Create symbolic link.

        For details see `._link`.
        '''
        return self._link(target, source, os.symlink)

    def _link(self, target, source, linkFunc):
        '''
        - if target without source
          - raises file not found error
        - if any target exists
          - raises file exists error
        - for all targets
          - creates parent directories as needed
          - links corresponding source to target
        '''
        sources = collections.OrderedDict(self._resolve(source))

        try:
            targets = self._resolve(target)

        except fuse.FuseOSError:  # targets not specified and don't exist
            targets = ((root, root + target) for root in sources)

        targets = collections.OrderedDict(targets)

        # len(targets) != 0

        if len(targets.keys() - sources.keys()) != 0:  # target without source
            raise fuse.FuseOSError(fuse.ENOENT)

        # targets is subset of sources

        for _, path in targets:
            if ospath.exists(path):
                raise fuse.FuseOSError(fuse.EEXIST)

        # no target exists

        for root, targetPath in reversed(targets.items()):
            self._ensure_directory(targetPath)
            r = linkFunc(sources[root], targetPath)

        return r

    @fuse_errors
    def truncate(self, path, length, fh=None):
        for _, p in reversed(self._resolve(path)):
            # from fusepy loopack example
            with open(p, 'r+') as f:
                r = f.truncate(length)

        return r

    @fuse_errors
    def unlink(self, path):
        for _, p in reversed(self._resolve(path)):
            r = os.unlink(p)

        return r

    @fuse_errors
    def utimens(self, path, times=None):
        for _, p in reversed(self._resolve(path)):
            r = os.utime(p, times=times)

        return r

    @fuse_errors
    def write(self, path, data, offset, fileHandle):
        with self._get_file_handle_lock(fileHandle):
            for fh in self._OpenFileHandles[fileHandle]:
                os.lseek(fh, offset, 0)  # from fusepy loopack example
                r = os.write(fh, data)

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

    def _get_file_handle_lock(self, fileHandle):
        with self._FileHandleLock:
            r = self._FileHandleLocks.get(fileHandle, None)
            if r is None:
                self._FileHandleLocks[fileHandle] = r = threading.Lock()

        return r

    def _ensure_directory(self, path):
        os.makedirs(ospath.dirname(path), exist_ok=True)


if __name__ == '__main__':
    import argparse
    import logging

    parser = argparse.ArgumentParser()

    parser.add_argument('-d', '--debug', action='store_true', default=False, help='Debug mode')
    parser.add_argument(
        metavar='root', nargs='+', dest='roots', help='Path of root directory as \'{character}={path}\'')
    parser.add_argument('dir', help='Path of directory to attach to')

    args = parser.parse_args()

    roots = []
    for root in args.roots:
        i = root.find('=')
        if i == -1:
            raise argparse.ArgumentError('root', 'Invalid root {}'.format(repr(root)))

        character = root[:i]
        path = root[(i + 1):]

        if not ospath.isdir(path):
            raise FileNotFoundError(path)

        roots.append((character, path))

    logging.basicConfig()

    fuse.FUSE(Mydfs(roots), args.dir, foreground=True, debug=args.debug)
