import math
import os
from typing import Tuple
from datetime import datetime, timedelta

import piexif
from tqdm import tqdm
import pandas as pd
from piexif import ExifIFD

from src.geo_utils import utm_to_deg


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


# https://gist.github.com/jeromer/2005586
# calc the yaw by 2 points
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
