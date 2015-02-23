#!/usr/bin/env python

from subprocess import *
import argparse
import os
import sys

from utilBMF.HTSUtils import PermissionError


def main():
    print(sys.argv)
    try:
        check_call(["python", "setup.py", "build_ext"])
    except CalledProcessError:
        print("Could not build C extensions. Abort!")
        return 1
    try:
        check_call(["python", "setup.py", "install"])
    except CalledProcessError:
        raise PermissionError("You might not have permission to install the "
                              "BMFTools packages.")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--prefix',
        help=("Will attempt to copy"
              " the main executable to the folder provided."
              " Defaults to /usr/local/bin"),
        default="/usr/local/bin")
    args = parser.parse_args()
    print("Now installing BMFMain in: " + args.prefix)
    try:
        check_call(["cp", "BMFMain/main.py", args.prefix + "/BMFMain"])
    except CalledProcessError:
        raise PermissionError("You might not have permission to install the "
                              "BMFMain executable.")
        return 1
    print("Now installing bmftools in: " + args.prefix)
    try:
        check_call(["cp", "utilBMF/bmftools.py", args.prefix + "/bmftools"])
    except CalledProcessError:
        raise PermissionError("You might not have permission to install the "
                              "BMFTools packages.")
    return 0


if(__name__ == "__main__"):
    main()
