#!/usr/bin/python

import os

def get_directory_size(directory):
    total_size = 0
    for dirpath, _, filenames in os.walk(directory):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            total_size += os.path.getsize(file_path)
    return total_size

def format_size(size):
    # Adapted from https://stackoverflow.com/a/1094933
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.2f} {units[index]}"

# Specify the directory path you want to count files in
directory_path = "PineScripts"

file_count = sum(len(files) for _, _, files in os.walk(directory_path))
directory_size = get_directory_size(directory_path)

print(f"The number of files in '{directory_path}' is: {file_count}")
print(f"The total size of the directory is: {format_size(directory_size)}")
