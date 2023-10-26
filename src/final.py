import os
from typing import List, Dict
from datetime import datetime, timedelta
from tqdm import tqdm
import pandas as pd

from src.validity_utils import remove_spaces, validate_csv_file
from src.utils import get_interpolated_location, extract_exif_date, extract_offset, calculate_initial_compass_bearing
from src.geo_utils import transform_to_wgs84


def parse_files(images_dirpath: str, legs_csv_filepath: str) -> None:
    legs_csv_filepath = remove_spaces(legs_csv_filepath)  # assures no spaces
    validation_issues = validate_csv_file(legs_csv_filepath)  # scans for possible issues

    # notifying about issues, asking to continue.
    if not validation_issues:
        print("CSV is valid.")
    else:
        print("Validation Issues:")
        for issue in validation_issues:
            print(issue)

        while True:
            user_input = input("Continue processing (y/n)? ").strip().lower()
            user_input = user_input[0]  # Get the first character entered
            if user_input == "y":
                print("Continuing...")
                break  # Valid input, exit the loop
            elif user_input == "n":
                print("Exiting...")
                exit(1)  # Exit the program
            else:
                print("Invalid input. Please enter 'y' or 'n'.")

    df: pd.DataFrame = pd.read_csv(legs_csv_filepath, index_col="time", parse_dates=True, date_format="%H:%M:%S")
    df: pd.DataFrame = df.fillna(method='ffill')
    df[["lon", "lat"]] = df["location"].str.split("/", expand=True).astype(float)
    offset: timedelta = extract_offset(df, images_dirpath)
    df.index = df.index - offset
    filenames: List[str] = sorted(os.listdir(images_dirpath), key=lambda x: extract_exif_date(f"{images_dirpath}/{x}"))

    csv_data: List[Dict] = []
    txt_file_data: List[Dict] = []
    failed_cnt: int = 0
    for i, filename in tqdm(enumerate(filenames), total=len(filenames)):
        try:
            filepath: str = f'{images_dirpath}/{filename}'
            date: datetime = extract_exif_date(filepath)
            lon, lat = get_interpolated_location(df, date)
            lon_wgs84, lat_wgs84 = transform_to_wgs84(lon, lat)
            loc: str = f"WGS84 GEO {lon_wgs84} E / {lat_wgs84} N"
            image_index = int(filename.lstrip('DSC').split('.')[0])
            csv_data.append({'loc': loc, 'Image_index': image_index})
        except Exception as e:
            print("An exception occurred")
            print(e)
            failed_cnt += 1
            print(f"{failed_cnt} / {i + 1} failed")
            print(f"File failed: {filename}")
            try:
                before = df[df.index <= date[-1]].iloc[-1]
                after = df[df.index > date[0]].iloc[-1]
                print(before['lon'], before['lat'])
                print(after['lon'], after['lat'])
            except:
                pass
            txt_file_data.append(txt_file_data[-1])
            txt_file_data[-2]['yaw'] = calculate_initial_compass_bearing(
                (txt_file_data[-2]['lon'], txt_file_data[-2]['lat']),
                (txt_file_data[-1]['lon'], txt_file_data[-1]['lat'])
            )
            continue

        txt_file_data.append({'lon': lon, 'lat': lat})
        if len(txt_file_data) == 1:
            continue

        txt_file_data[-2]['yaw'] = calculate_initial_compass_bearing(
            (txt_file_data[-2]['lon'], txt_file_data[-2]['lat']),
            (txt_file_data[-1]['lon'], txt_file_data[-1]['lat'])
        )

    pd.DataFrame.from_records(csv_data).to_csv(f'full_WGS84_output.csv', index=True)

    txt_file_lines: List[str] = []
    print(txt_file_data[-1], txt_file_data[-2])
    txt_file_data[-1]['yaw'] = txt_file_data[-2]['yaw']
    for datapoint in txt_file_data:
        txt_file_lines.append(f"relative_alt: 400.00, roll: 0.00, pitch: 0.00, yaw: {datapoint['yaw'] - 90}, "
                              f"lat: {datapoint['lat']}, lon: {datapoint['lon']}")
        txt_file_lines += ['trigger'] * 3

    txt_file_lines.append(txt_file_lines[-4])
    with open(f'triggers1.txt', 'w') as f:
        f.write('\n'.join(txt_file_lines))
