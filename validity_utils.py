import csv
import os
from datetime import datetime
from typing import Optional

import pandas as pd
import numpy as np

from utils import parse_time


def remove_spaces(input_file):
    output_file = os.path.splitext(input_file)[0] + '_corrected.csv'

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


def delete_empty_rows(csv_filepath: str) -> None:
    df: pd.DataFrame = pd.read_csv(csv_filepath)
    df = df.replace('', np.nan)
    df = df.dropna(axis=0, subset=['location', 'time'], how='any')
    df.to_csv(csv_filepath, index=False)


# Validation function for the 'location' column
def is_valid_location(location):
    parts = location.split('/')
    if len(parts) != 2:
        return False

    return len(parts[0]) == 6 and len(parts[1]) == 7 and parts[0].isdigit() and parts[1].isdigit()


# Validation function for the 'time' column format
def is_valid_time_format(time):
    return time.count(':') == 2


# Validation function for checking if a time is in chronological order
def is_valid_time_range(time: datetime, previous_time: datetime):
    return time > previous_time


# Main validation function for the CSV file
def validate_csv_file(input_file):
    issues = []  # Collect issues during validation
    previous_time: Optional[datetime] = None

    with open(input_file, 'r', newline='') as infile:
        reader = csv.reader(infile)
        next(reader)  # skipping the titles
        for i, row in enumerate(reader, start=2):
            if not row or len(row) < 2:
                continue

            location, time = row[0], row[1]
            time: str
            time: Optional[datetime] = parse_time(time)

            if not time:
                issues.append(f"Issue at {i}: Time Format Error")

            if not is_valid_location(location):
                issues.append(f"Issue at {i}: Location Format Error")

            if previous_time:
                if not is_valid_time_range(time, previous_time):
                    issues.append(f"Issue at {i}: Time Chronological Disruption")

            previous_time = time

    return issues
