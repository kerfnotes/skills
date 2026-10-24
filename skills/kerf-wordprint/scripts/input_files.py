"""Pinned, no-follow directories for local input copies (standard library only)."""
from contextlib import contextmanager
import errno
import os
from pathlib import Path
import stat


def require_dir_fd():
    supported = {function.__name__ for function in os.supports_dir_fd}
    if (not {'open', 'stat', 'mkdir', 'rename', 'unlink'} <= supported or
            'stat' not in {function.__name__ for function in os.supports_follow_symlinks} or
            not all(hasattr(os, flag) for flag in ('O_DIRECTORY', 'O_NOFOLLOW', 'O_NONBLOCK')) or
            not hasattr(os, 'fchmod')):
        raise ValueError('此平台不支援安全的目錄 fd 匯入；語音備忘錄請在 macOS 使用，表單上傳已停用。')


@contextmanager
def fixed_directory(path, *, parent_fd=None, verify_parent=None):
    """Yield (fd, verify_binding); callers verify before publishing/returning."""
    require_dir_fd()
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                             dir_fd=parent_fd)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR):
            raise ValueError('錄音保存位置／來源／上傳目錄無效，不接受符號連結。') from error
        raise
    try:
        identity = os.fstat(descriptor)
        def verify():
            if verify_parent:
                verify_parent()
            current = os.stat(path, dir_fd=parent_fd, follow_symlinks=False)
            if (not stat.S_ISDIR(current.st_mode) or
                    (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino)):
                raise ValueError('錄音保存位置／來源／上傳目錄發生變動，請重新操作。')
        verify()
        yield descriptor, verify
    finally:
        os.close(descriptor)


@contextmanager
def inputs_directory(task):
    """Pin both task and inputs; never chmod a replacement directory target."""
    task = Path(os.path.abspath(task))
    with fixed_directory(task) as (task_fd, verify_task):
        try:
            os.mkdir('inputs', mode=0o700, dir_fd=task_fd)
        except FileExistsError:
            pass
        with fixed_directory('inputs', parent_fd=task_fd,
                             verify_parent=verify_task) as (descriptor, verify):
            os.fchmod(descriptor, 0o700)
            verify()
            yield descriptor, verify


def create_file(directory_fd, name):
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory_fd)
    try:
        os.fchmod(descriptor, 0o600)
        return os.fdopen(descriptor, 'wb')
    except BaseException:
        os.close(descriptor)
        remove_file(directory_fd, name)
        raise


def remove_file(directory_fd, name):
    if name is not None:
        try:
            os.unlink(name, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
