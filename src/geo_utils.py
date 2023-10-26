import utm


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


def transform_to_wgs84(lon, lat) -> tuple[float, float]:
    # Define source coordinate system and WGS84 system
    lat, lon = utm.to_latlon(easting=lon, northing=lat, zone_number=36, zone_letter='T')
    return lon, lat
