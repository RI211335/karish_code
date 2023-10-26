import csv
import os
from datetime import datetime
from typing import List


def remove_spaces(input_file):
    output_file = os.path.splitext(input_file)[0] + '_no_spaces.csv'

    with open(input_file, 'r', newline='') as infile, open(output_file, 'w', newline='') as outfile:
        reader = csv.reader(infile)
        writer = csv.writer(outfile)

        for row in reader:
            if row:  # assures no empty lines
                if len(row) >= 2:
                    location = row[0].replace(" ", "")
                    time = row[1].replace(" ", "")
                    new_row = [location, time] + row[2:]  # affects only first two columns
                    writer.writerow(new_row)

    return output_file


# Validation function for the 'location' column
def is_valid_location(location):
    parts = location.split('/')
    if len(parts) != 2:
        return False
    return len(parts[0]) == 6 and len(parts[1]) == 7 and parts[0].isdigit() and parts[1].isdigit()


# Validation function for the 'time' column format
def is_valid_time_format(time):
    return len(time) == 8 and time.count(':') == 2


# Validation function for checking if a time is in chronological order
def is_valid_time_range(time: str, times: List[str]):
    if not times:
        return True
    time_obj = datetime.strptime(time, '%H:%M:%S')
    max_time_obj = max((datetime.strptime(t, '%H:%M:%S') for t in times))
    return time_obj > max_time_obj


# Main validation function for the CSV file
def validate_csv_file(input_file):
    start_time = None  # Initialize start_time to None

    issues = []  # Collect issues during validation

    with open(input_file, 'r', newline='') as infile:
        reader = csv.reader(infile)
        next(reader)  # skipping the titles
        times = []
        for i, row in enumerate(reader, start=2):
            if len(row) >= 2:
                location, time = row[0], row[1]

                if not is_valid_location(location):
                    issues.append(f"Issue at {i}: Location- Format")

                if not is_valid_time_format(time):
                    issues.append(f"Issue at {i}: Time- Format")

                if not is_valid_time_range(time, times):
                    issues.append(f"Issue at {i}: Time- Chronological Disruption")

                if start_time is None:
                    start_time = time  # Assign the first valid time as the start_time

                times.append(time)

    return issues
