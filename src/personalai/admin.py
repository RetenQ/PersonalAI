"""Run locally on the server; never place administrator passwords in argv."""
import argparse
import getpass
import os
from pathlib import Path
from .access import Access
from .store import Store

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='初始化单用户网页登录；已有账户不会被覆盖。')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--generate-master-key', type=Path, help='生成独立的 32 字节保护密钥；禁止覆盖已有文件')
    args = parser.parse_args()
    if args.generate_master_key:
        path = args.generate_master_key.resolve()
        project = Path(__file__).resolve().parents[2]
        if project == path or project in path.parents or args.data_dir and args.data_dir.resolve() in path.parents:
            parser.error('保护密钥必须保存在代码仓库和数据目录之外。')
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
            handle.write(os.urandom(32)); handle.flush(); os.fsync(handle.fileno())
        print('Independent master key created. Protect it separately; never commit it.')
        raise SystemExit(0)
    if not args.data_dir: parser.error('--data-dir is required to initialize owner')
    password = getpass.getpass('New owner password (12+ characters): ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords do not match')
    Access(Store(args.data_dir)).initialize(password)
    password = None
    print('Owner initialized. Web login is now required for this data directory.')
