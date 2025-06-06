#!/usr/bin/env python3
"""Resize an image to a given width and height."""
import argparse
from PIL import Image

def main():
    parser = argparse.ArgumentParser(description="Resize an image")
    parser.add_argument("input", help="Path to input image")
    parser.add_argument("output", help="Path to save resized image")
    parser.add_argument("--width", type=int, default=100, help="Target width")
    parser.add_argument("--height", type=int, default=100, help="Target height")
    args = parser.parse_args()

    img = Image.open(args.input)
    img = img.resize((args.width, args.height))
    img.save(args.output)
    print(f"Saved resized image to {args.output}")

if __name__ == "__main__":
    main()
