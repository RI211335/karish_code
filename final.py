import math
import os
from typing import Tuple, List, Dict
from datetime import datetime, timedelta
from validity_utils import remove_spaces, validate_csv_file
import piexif
from tqdm import tqdm
import pandas as pd
from piexif import ExifIFD
import utm


def interpolate_geo(coord1: Tuple[float, float], coord2: Tuple[float, float], fraction: float):
    # Extract longitudes and latitudes
    lon1, lat1 = coord1
    lon2, lat2 = coord2

    return (1 - fraction) * lon1 + fraction * lon2, (1 - fraction) * lat1 + fraction * lat2


def get_interpolated_location(df: pd.DataFrame, date: datetime) -> Tuple[float, float]:
    try:
        before = df[df.index <= date].iloc[-1]
    except IndexError:
        raise Exception("No data before date")
    try:
        after = df[df.index >= date].iloc[0]
    except IndexError:
        raise Exception("No data after date")

    if before.name == after.name:
        return before['lon'], before['lat']

    # Calculate the interpolation fraction
    fraction = (date - before.name) / (after.name - before.name)
    coord1 = (before['lon'], before['lat'])
    coord2 = (after['lon'], after['lat'])

    # Get the interpolated coordinates
    lon, lat = interpolate_geo(coord1, coord2, fraction)
    return lon, lat


def utm_to_deg(value, loc):
    if value < 0:
        loc_value = loc[0]
    else:
        loc_value = loc[1]

    abs_value = abs(value)
    deg = int(abs_value)
    min = int((abs_value - deg) * 60)
    sec = int((abs_value - deg - min / 60) * 3600)

    return deg, min, sec, loc_value


def transform_to_wgs84(lon, lat) -> Tuple[float, float]:
    # Define source coordinate system and WGS84 system
    lat, lon = utm.to_latlon(easting=lon, northing=lat, zone_number=36, zone_letter='T')
    return lon, lat


# https://gist.github.com/jeromer/2005586
def calculate_initial_compass_bearing(pointA, pointB):
    if (type(pointA) != tuple) or (type(pointB) != tuple):
        raise TypeError("Only tuples are supported as arguments")

    lat1 = math.radians(pointA[0])
    lat2 = math.radians(pointB[0])

    diffLong = math.radians(pointB[1] - pointA[1])

    x = math.sin(diffLong) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1)
            * math.cos(lat2) * math.cos(diffLong))

    initial_bearing = math.atan2(x, y)

    # Now we have the initial bearing but math.atan2 return values
    # from -180° to + 180° which is not what we want for a compass bearing
    # The solution is to normalize the initial bearing as shown below
    initial_bearing = math.degrees(initial_bearing)
    compass_bearing = (initial_bearing + 360) % 360

    return compass_bearing


def extract_exif_date(input_filepath: str) -> datetime:
    exif_dict = piexif.load(input_filepath)
    date_str: str = exif_dict['0th'][piexif.ImageIFD.DateTime].decode('utf-8')
    date: datetime = datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
    date_str: str = date.strftime('%H:%M:%S')
    return datetime.strptime(date_str, '%H:%M:%S')


def set_image_exif(df: pd.DataFrame, input_filepath: str, output_filepath: str) -> None:
    exif_dict = piexif.load(input_filepath)
    # Convert degrees to (degree, minute, second)

    date: datetime = extract_exif_date(input_filepath)
    lon, lat = get_interpolated_location(df, date)

    # Format latitude and longitude
    lat_deg = utm_to_deg(lat, ["S", "N"])
    lon_deg = utm_to_deg(lon, ["W", "E"])

    exif_dict["GPS"][piexif.GPSIFD.GPSLatitudeRef] = lat_deg[3].encode('utf-8')
    exif_dict["GPS"][piexif.GPSIFD.GPSLatitude] = [(lat_deg[0], 1), (lat_deg[1], 1), (lat_deg[2] * 100, 100)]
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitudeRef] = lon_deg[3].encode('utf-8')
    exif_dict["GPS"][piexif.GPSIFD.GPSLongitude] = [(lon_deg[0], 1), (lon_deg[1], 1), (lon_deg[2] * 100, 100)]
    absolute_height = "Absolute Height: 500m"
    exif_dict["Exif"][ExifIFD.UserComment] = absolute_height.encode()
    view_angle = "View Angle: 0 degrees"
    exif_dict["Exif"][ExifIFD.MakerNote] = view_angle.encode()

    # Convert the updated EXIF data to bytes
    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, input_filepath, output_filepath)


def extract_offset(df: pd.DataFrame, dirpath: str) -> timedelta:
    min_df_time = df.index.min()
    min_image_time = min([extract_exif_date(f'{dirpath}/{filename}') for filename in tqdm(os.listdir(dirpath))])
    return min_df_time - min_image_time


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
            print(f"{failed_cnt} / {i+1} failed")
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


if __name__ == "__main__":
    parse_files(images_dirpath=r"E:\24102023_north_1\SD1\DCIM\100MSDCF",
                legs_csv_filepath=r"C:\Users\aribi\Desktop\test_l\לידר 2410_1n.csv")
