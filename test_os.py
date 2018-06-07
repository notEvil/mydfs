import hypothesis as hy
import hypothesis.strategies as hys
import hypothesis_fs
import pytest
import logging
import os
import contextlib
import stat
ospath = os.path


@hys.composite
def _choices(draw,
             n,
             withATime=False,
             withMTime=False,
             withUser=False,
             withGroup=False,
             withMode=False,
             withContent=False):
    directory = draw(
        hypothesis_fs.directories(
            withATime=withATime,
            withMTime=withMTime,
            withUser=withUser,
            withGroup=withGroup,
            withMode=withMode,
            withContent=withContent,
        ).filter(lambda directory: len(directory.ExistingFiles) != 0 or len(directory.NotExistingFiles) != 0))
    choices = draw(hys.lists(hypothesis_fs.choose(directory), min_size=n, max_size=n))
    r = directory, choices
    return r


@contextlib.contextmanager
def context(directory):
    # logging.info(directory)

    with hypothesis_fs.Context(directory, './test'):
        yield './test'

        directory.assert_('./test')


@hy.given(_choices(1))
def test_listdir(args):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                os.listdir(p)

        elif not isinstance(file, hypothesis_fs.Directory):
            with pytest.raises(NotADirectoryError):
                os.listdir(p)

        else:
            names = set(os.listdir(p))
            expected = file.ExistingFiles.keys()

            if file.ExistingFilesComplete:
                assert names == expected

            else:
                assert names.issuperset(expected)


@hy.given(_choices(1))
def test_mkdir(args):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if exists:
            with pytest.raises(FileExistsError):
                os.mkdir(p)

        elif not ospath.exists(ospath.dirname(p)):
            with pytest.raises(FileNotFoundError):
                os.mkdir(p)

        else:
            os.mkdir(p)

            d, name = _get_directory_and_name(path, directory)
            d[name] = hypothesis_fs.Directory({}, True, {})


@hy.given(_choices(1))
def test_remove(args):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                os.remove(p)

        elif isinstance(file, hypothesis_fs.Directory):
            with pytest.raises(IsADirectoryError):
                os.remove(p)

        else:
            os.remove(p)

            d, name = _get_directory_and_name(path, directory)
            del d[name]


@hy.given(_choices(1))
def test_rmdir(args):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                os.rmdir(p)

        elif not isinstance(file, hypothesis_fs.Directory):
            with pytest.raises(NotADirectoryError):
                os.rmdir(p)

        else:
            if len(file.ExistingFiles) == 0:
                os.rmdir(p)

                d, name = _get_directory_and_name(path, directory)
                del d[name]

            else:
                with pytest.raises(OSError, match='Directory not empty'):
                    os.rmdir(p)


@hy.given(_choices(2))
def test_rename(args):
    directory, ((sourcePath, sourceFile, sourceExists), (destPath, destFile, destExists)) = args

    with context(directory) as basePath:
        sPath = ospath.join(basePath, sourcePath)
        dPath = ospath.join(basePath, destPath)

        if False:
            pass

        elif not sourceExists or not ospath.exists(ospath.dirname(dPath)):  # source doesn't exist
            with pytest.raises(FileNotFoundError):
                os.rename(sPath, dPath)

        elif destPath.startswith(sourcePath + '/'):  # move directory into itself
            with pytest.raises(OSError, match='Invalid argument'):
                os.rename(sPath, dPath)

        elif isinstance(sourceFile, hypothesis_fs.RegularFile) and isinstance(
                destFile, hypothesis_fs.Directory) and destExists:  # file -> directory
            with pytest.raises(OSError, match='(Is a directory)|(Directory not empty)'):
                os.rename(sPath, dPath)

        elif isinstance(sourceFile, hypothesis_fs.Directory) and not isinstance(
                destFile, hypothesis_fs.Directory) and destExists:  # directory -> not directory
            with pytest.raises(NotADirectoryError):
                os.rename(sPath, dPath)

        elif isinstance(sourceFile, hypothesis_fs.Directory) and isinstance(
                destFile, hypothesis_fs.Directory
        ) and destExists and sourcePath != destPath and len(destFile) != 0:  # directory -> directory
            with pytest.raises(OSError, match='Directory not empty'):
                os.rename(sPath, dPath)

        else:
            os.rename(sPath, dPath)

            if sourceFile is destFile and destExists:
                pass

            else:
                sourceDirectory, sourceName = _get_directory_and_name(sourcePath, directory)
                destDirectory, destName = _get_directory_and_name(destPath, directory)
                destDirectory[destName] = sourceDirectory.pop(sourceName)


def _get_directory_and_name(path, directory):
    names = path.split('/')

    for name in names[:-1]:
        directory = directory[name]

    name = names[-1]

    r = directory, name
    return r


@hy.given(_choices(2))
def test_link(args):
    directory, ((sourcePath, sourceFile, sourceExists), (destPath, destFile, destExists)) = args

    with context(directory) as basePath:
        sPath = ospath.join(basePath, sourcePath)
        dPath = ospath.join(basePath, destPath)

        if False:
            pass

        elif not sourceExists or not ospath.exists(ospath.dirname(dPath)):
            with pytest.raises(FileNotFoundError):
                os.link(sPath, dPath)

        elif destExists:
            with pytest.raises(FileExistsError):
                os.link(sPath, dPath)

        elif isinstance(sourceFile, hypothesis_fs.Directory):
            with pytest.raises(PermissionError):
                os.link(sPath, dPath)

        else:
            os.link(sPath, dPath)

            destDirectory, destName = _get_directory_and_name(destPath, directory)

            destDirectory[destName] = sourceFile


@hy.given(_choices(1, withATime=True, withMTime=True, withUser=True, withGroup=True, withMode=True))
def test_stat(args):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                stat_ = os.stat(p)

        else:
            stat_ = os.stat(p)

            assert stat_.st_atime_ns == file.ATime
            assert stat_.st_mtime_ns == file.MTime
            assert stat.S_IMODE(stat_.st_mode) == file.Mode


@hys.composite
def _modes(draw):
    parts = draw(hys.just(os.F_OK) | hypothesis_fs.subsets([os.R_OK, os.W_OK, os.X_OK]))

    if parts == os.F_OK:
        return os.F_OK

    r = 0
    for part in parts:
        r |= part

    return r


_modes = _modes()


@hy.given(_choices(1, withUser=True, withGroup=True, withMode=True), _modes)
def test_access(args, mode):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        r = os.access(p, mode)

        if mode == os.F_OK:
            assert r == exists


@hy.given(_choices(1, withATime=True, withMTime=True), hypothesis_fs.times, hypothesis_fs.times)
def test_utime(args, aTime, mTime):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                os.utime(p, ns=(aTime, mTime))

        else:
            os.utime(p, ns=(aTime, mTime))

            file.ATime = aTime
            file.MTime = mTime


@hy.given(
    _choices(1, withUser=True, withGroup=True),
    hys.just(-1) | hypothesis_fs.users,
    hys.just(-1) | hypothesis_fs.groups)
def test_chown(args, user, group):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                os.chown(p, user, group)

        else:
            os.chown(p, user, group)

            if user != -1:
                file.User = user

            if group != -1:
                file.Group = group


@hy.given(_choices(1, withMode=True), hypothesis_fs.modes)
def test_chmod(args, mode):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                os.chmod(p, mode)

        else:
            os.chmod(p, mode)

            file.Mode = mode


@hy.given(_choices(1))
def test_open_close(args):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                with open(p):
                    pass

        elif isinstance(file, hypothesis_fs.Directory):
            with pytest.raises(IsADirectoryError):
                with open(p):
                    pass

        else:
            with open(p):
                pass


@hy.given(_choices(1, withContent=True), hys.floats(min_value=0, max_value=1), hys.floats(min_value=0, max_value=1))
def test_read(args, offset, length):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                with open(p, 'rb'):
                    pass

        elif isinstance(file, hypothesis_fs.Directory):
            with pytest.raises(IsADirectoryError):
                with open(p, 'rb'):
                    pass

        else:
            offset = int(offset * file.Size)
            length = int(length * (file.Size - offset))

            with open(p, 'rb') as f:
                f.seek(offset)

                content = f.read(length)

            assert content == file.Content[offset:(offset + length)]


@hy.given(_choices(1, withContent=True), hys.floats(min_value=0, max_value=1), hypothesis_fs.contents)
def test_write(args, offset, content):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                with open(p, 'rb'):
                    pass

        elif isinstance(file, hypothesis_fs.Directory):
            with pytest.raises(IsADirectoryError):
                with open(p, 'rb'):
                    pass

        else:
            offset = int(offset * file.Size)

            with open(p, 'r+b') as f:
                f.seek(offset)

                f.write(content)

            file.Content = b''.join([file.Content[:offset], content, file.Content[(offset + len(content)):]])
            file.Size = len(file.Content)


@hy.given(_choices(1, withContent=True), hys.floats(min_value=0, max_value=2))
def test_truncate(args, length):
    directory, ((path, file, exists), ) = args

    with context(directory) as basePath:
        p = ospath.join(basePath, path)

        if not exists:
            with pytest.raises(FileNotFoundError):
                os.truncate(p, 0)

        elif isinstance(file, hypothesis_fs.Directory):
            with pytest.raises(IsADirectoryError):
                os.truncate(p, 0)

        else:
            length = int(length * file.Size)

            os.truncate(p, length)

            file.Content = file.Content[:length] + b'\0' * max(0, length - file.Size)
            file.Size = len(file.Content)
