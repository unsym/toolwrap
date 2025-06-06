#!/usr/bin/env python3
"""Add two matrices of the same size."""
import argparse
import numpy as np

def main():
    parser = argparse.ArgumentParser(description="Add two matrices")
    parser.add_argument("--size", type=int, default=2, help="Matrix dimension")
    args = parser.parse_args()
    a = np.arange(args.size**2).reshape(args.size, args.size)
    b = np.ones((args.size, args.size))
    result = a + b
    print(result)

if __name__ == "__main__":
    main()
