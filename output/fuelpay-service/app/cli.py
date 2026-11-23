"""Operator command line.

    python -m app.cli create-admin --email ops@example.com --name "Ada" --role OWNER

The password is prompted for (twice) and never echoed or passed on the
command line, where it would land in shell history.
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy.exc import IntegrityError

from app.db import dispose_engine, get_sessionmaker
from app.models.entities import AdminRole
from app.services.admin_auth import create_admin, password_problem


async def _create_admin(email: str, name: str, role: AdminRole, password: str) -> int:
    async with get_sessionmaker()() as session:
        try:
            user = await create_admin(session, email, name, password, role)
            await session.commit()
        except IntegrityError:
            print(f"An admin with email {email!r} already exists.", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    await dispose_engine()
    print(f"Created {user.role.value} {user.email}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="Add a platform admin")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", choices=[r.value for r in AdminRole], default="OWNER")
    create.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from stdin instead of prompting (for automation).",
    )
    args = parser.parse_args(argv)

    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords do not match.", file=sys.stderr)
            return 1
    problem = password_problem(password)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    return asyncio.run(_create_admin(args.email, args.name, AdminRole(args.role), password))


if __name__ == "__main__":
    sys.exit(main())
