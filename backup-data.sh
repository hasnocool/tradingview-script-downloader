#!/bin/bash

# Set the source directory and filename
source_dir="PineScripts"
filename="Backups/PineScripts_$(date +'%Y%m%d_%H%M%S').tar.gz"
cleaned_source_dir="PineScripts_Cleaned"
cleaned_filename="Backups/PineScripts_Cleaned_$(date +'%Y%m%d_%H%M%S').tar.gz"
# Create the tar.gz archive
tar -czf "$filename" "$source_dir"
tar -czf "$cleaned_filename" "$cleaned_source_dir"
echo "Archive created: $filename"
echo "Archive created: $cleaned_filename"
