import mydfs
import fuse
import os
import argparse
import logging
ospath = os.path

# parse arguments
parser = argparse.ArgumentParser()

parser.add_argument('-d', '--debug', action='store_true', default=False, help='Debug mode')
parser.add_argument(metavar='root', nargs='+', dest='roots', help='Path of root directory as \'{character}={path}\'')
parser.add_argument('dir', help='Path of directory to attach to')

args = parser.parse_args()
#

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

fuse.FUSE(mydfs.Mydfs(roots), args.dir, foreground=True, debug=args.debug)
