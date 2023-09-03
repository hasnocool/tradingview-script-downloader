#!/usr/bin/python

import os
import re

# Function to clean the PineScript
def clean_pinescript(script):
    lines = script.split('\n')

    # Remove numbered lines dynamically
    lines = [line for line in lines if not re.match(r"^\d+\s*$", line.strip())]

    copy_code_index = next(
        (i for i, line in enumerate(lines) if line.strip() == 'Copy code'), -1
    )
    # Remove the last line if it contains the word "Expand" followed by parentheses and a number
    if re.match(r"Expand \(\d+ lines\)", lines[-1].strip()):
        lines = lines[:-1]

    # Add comments to the lines preceding "Copy code"
    comment_lines = []
    for i in range(copy_code_index):
        if line := lines[i].strip():
            comment_lines.append(f"// {line}")
    lines = comment_lines + lines[copy_code_index + 1:]

    # Remove unnecessary lines and format PineScript code properly
    cleaned_script = '\n'.join(lines).strip()
    cleaned_script = cleaned_script.replace('\n\n', '\n')
    cleaned_script = cleaned_script.replace('=', ' = ')
    cleaned_script = cleaned_script.replace(':', ': ')
    return cleaned_script.replace('  ', ' ')

# Specify the folder paths
input_folder = 'PineScripts'
output_folder = 'PineScripts_Cleaned'

# Create the output folder if it doesn't exist
os.makedirs(output_folder, exist_ok=True)

# Iterate through the files in the input folder
for file_name in os.listdir(input_folder):
    if file_name.endswith('.pine'):
        input_file_path = os.path.join(input_folder, file_name)
        output_file_path = os.path.join(output_folder, file_name)
        
        with open(input_file_path, 'r') as file:
            script = file.read()
        
        cleaned_script = clean_pinescript(script)
        
        with open(output_file_path, 'w') as cleaned_file:
            cleaned_file.write(cleaned_script)
        
        print(f"Cleaned script saved to: {output_file_path}")
