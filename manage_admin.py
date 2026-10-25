"""Create/reset the single administrator using local console access."""
import argparse
import getpass
from pathlib import Path
from admin_auth import AuthStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['init', 'reset-password'])
    parser.add_argument('--username', default='admin')
    args = parser.parse_args()
    password = getpass.getpass('管理员密码（至少 12 字符）: ')
    if password != getpass.getpass('再次输入密码: '):
        parser.error('两次输入的密码不同')
    store = AuthStore(Path(__file__).resolve().parent/'admin_auth.sqlite3')
    try:
        if args.action == 'init':store.create_admin(args.username, password)
        else:store.reset_password(password)
    except Exception as error:
        parser.exit(1, str(error)+'\n')
    print('管理员已保存；密码重置将撤销全部旧会话。')


if __name__ == '__main__':
    main()
