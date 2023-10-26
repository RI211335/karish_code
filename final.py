import math
import os
from typing import Tuple, List, Dict
from datetime import datetime, timedelta
import piexif
from tqdm import tqdm
import pandas as pd
from piexif import ExifIFD
import piexif._exceptions
import utm


from validity_utils import remove_spaces, validate_csv_file, delete_empty_rows


def interpolate_coords(coord1: Tuple[float, float], coord2: Tuple[float, float], fraction: float):
    # Extract longitudes and latitudes
    lon1, lat1 = coord1
    lon2, lat2 = coord2

    return (1 - fraction) * lon1 + fraction * lon2, (1 - fraction) * lat1 + fraction * lat2


def get_interpolated_location(df: pd.DataFrame, date: datetime) -> Tuple[float, float]:
    before = df[df.index <= date].iloc[-1]
    after = df[df.index >= date].iloc[0]

    if before.name == after.name:
        return before['lon'], before['lat']

    # Calculate the interpolation fraction
    fraction = (date - before.name) / (after.name - before.name)
    coord1 = (before['lon'], before['lat'])
    coord2 = (after['lon'], after['lat'])

    # Get the interpolated coordinates
    lon, lat = interpolate_coords(coord1, coord2, fraction)
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
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1) * math.cos(lat2) * math.cos(diffLong))

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


def set_image_exif(input_filepath: str, output_filepath: str, lon: float, lat: float) -> None:
    exif_dict = piexif.load(input_filepath)

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


def lidar_preprocess(lidar_filepath: str) -> str:
    lidar_processed_filepath: str = remove_spaces(lidar_filepath)  # assures no spaces
    delete_empty_rows(lidar_processed_filepath)
    validation_issues = validate_csv_file(lidar_processed_filepath)  # scans for possible issues

    # notifying about issues, asking to continue.
    if not validation_issues:
        print("CSV is valid.")
        return lidar_filepath
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

    return lidar_processed_filepath

def extract_offset(df: pd.DataFrame, valid_files: List[Dict]) -> timedelta:
    min_df_time: datetime = df.index.min()
    min_image_time: datetime = min(valid_files, key=lambda x: x['date'])['date']
    return min_df_time - min_image_time


def exception_start_handler(filename: str, e: Exception, parsed_data: List[Dict]):
    print("An exception occurred")
    print(e)
    print(f"File failed: {filename}")
    last_parsed_line: Dict = parsed_data[-1]
    parsed_data.append({**last_parsed_line, 'is_valid': False})


def add_latest_yaw(parsed_data: List[Dict]):
    if len(parsed_data) == 1:
        return

    parsed_data[-2]['yaw'] = calculate_initial_compass_bearing(
        (parsed_data[-2]['lon'], parsed_data[-2]['lat']),
        (parsed_data[-1]['lon'], parsed_data[-1]['lat'])
    )


def create_output_csv(parsed_data: List[Dict], output_filepath: str) -> None:
    filtered_parsed_data: List[Dict] = list(filter(lambda x: x['is_valid'], parsed_data))
    df: pd.DataFrame = pd.DataFrame.from_records(filtered_parsed_data)
    df: pd.DataFrame = df[['loc', 'Image_index']]
    df.to_csv(output_filepath, index=True)


def create_txt_file(parsed_data: List[Dict], output_filepath: str) -> None:
    txt_file_lines: List[str] = []
    parsed_data[-1]['yaw'] = parsed_data[-2]['yaw']
    for datapoint in parsed_data:
        txt_file_lines.append(f"relative_alt: 400.00, roll: 0.00, pitch: 0.00, yaw: {datapoint['yaw'] - 90}, "
                              f"lat: {datapoint['lat']}, lon: {datapoint['lon']}")
        txt_file_lines += ['trigger'] * 3

    txt_file_lines.append(txt_file_lines[-4])
    with open(output_filepath, 'w') as f:
        f.write('\n'.join(txt_file_lines))


def parse_files(images_dirpath: str, lidar_filepath: str, set_images_exif: bool) -> None:
    base_csv_filename = os.path.splitext(os.path.basename(lidar_filepath))[0]
    csv_output_path: str = f'{base_csv_filename}_WGS84_full_output.csv'
    txt_output_path: str = f'{base_csv_filename}_triggers.txt'
    lidar_processed_filepath: str = lidar_preprocess(lidar_filepath)

    valid_files: List[Dict] = []
    for filename in os.listdir(images_dirpath):
        try:
            valid_files.append({
                'filename': filename,
                'date': extract_exif_date(f"{images_dirpath}/{filename}")
            })
        except piexif._exceptions.InvalidImageDataError:
            continue

    valid_files: List[Dict] = sorted(valid_files, key=lambda x: x['date'])

    df: pd.DataFrame = pd.read_csv(lidar_processed_filepath, index_col="time", parse_dates=True, infer_datetime_format=True)
    df: pd.DataFrame = df.fillna(method='ffill')
    df[["lon", "lat"]] = df["location"].str.split("/", expand=True).astype(float)
    offset: timedelta = extract_offset(df, valid_files)
    df.index = df.index - offset

    failed_cnt: int = 0
    parsed_data: List[Dict] = []
    for i, file in tqdm(enumerate(valid_files), total=len(valid_files)):
        filename: str = file['filename']
        date: datetime = file['date']
        filepath: str = f'{images_dirpath}/{filename}'

        try:
            lon, lat = get_interpolated_location(df, date)
            lon_wgs84, lat_wgs84 = transform_to_wgs84(lon, lat)
            loc: str = f"WGS84 GEO {lon_wgs84} E / {lat_wgs84} N"
            image_index: int = int(filename.lstrip('DSC').split('.')[0])
            parsed_data.append({'loc': loc, 'Image_index': image_index, 'lon': lon, 'lat': lat, 'is_valid': True})
            if set_images_exif:
                set_image_exif(filepath, filepath, lon, lat)
        except IndexError as e:
            failed_cnt += 1
            exception_start_handler(filename, e, parsed_data)
            print(f"{failed_cnt} / {len(valid_files)} failed")
        except utm.error.OutOfRangeError as e:
            failed_cnt += 1
            exception_start_handler(filename, e, parsed_data)
            before = df[df.index <= date].iloc[-1]
            after = df[df.index >= date].iloc[-1]
            print(before['lon'], before['lat'])
            print(after['lon'], after['lat'])
            print(f"{failed_cnt} / {len(valid_files)} failed")
        except Exception as e:
            failed_cnt += 1
            exception_start_handler(filename, e, parsed_data)
            print(f"{failed_cnt} / {len(valid_files)} failed")
        finally:
            add_latest_yaw(parsed_data)

    create_output_csv(parsed_data, csv_output_path)
    create_txt_file(parsed_data, txt_output_path)


if __name__ == "__main__":
    parse_files(
        images_dirpath=r"./images",
        lidar_filepath=r"legs_error.csv",
        set_images_exif=False
    )
