#!/usr/bin/env python

from subprocess import *
import argparse
import sys


def main():
    print(sys.argv)
    dir = "/".join(sys.argv[0].split("/")[0:-1])
    try:
        check_call(["python", dir + "/setup.py", "install"])
    except CalledProcessError:
        print("You might not have permission to install the BMFTools packages.")
        return 1
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--prefix',
        help=("Will attempt to copy"
        " the main executable to the folder provided."
        " Defaults to /usr/local/bin"),
        default="/usr/local/bin"
        )
    args = parser.parse_args()
    try:
        check_call(["cp", "BMFMain/main.py", args.prefix + "/bmftools"])
    except CalledProcessError:
        print("You might not have permission to install the bmftools executable.")
        return 1
    return


if(__name__ == "__main__"):
    main()
