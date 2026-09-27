"""Static reference data for the MOIL study area.

Mine names, districts and mining methods follow MOIL's public profile (moil.nic.in).
Coordinates are approximate (±2-3 km, for visualisation only) and capacities/grades are
indicative figures scaled so that the ten-mine total is of the same order as MOIL's
publicly reported annual output (~1.5-1.8 Mt/yr). They are NOT MOIL internal figures.
"""

STUDY_BBOX = {"lat_min": 21.20, "lat_max": 22.10, "lon_min": 78.80, "lon_max": 80.60}

CLUSTERS = {
    "NGP": "Nagpur cluster (Maharashtra)",
    "BHD": "Bhandara cluster (Maharashtra)",
    "BLG": "Balaghat cluster (Madhya Pradesh)",
}

# rated_capacity_tpd: indicative run-of-mine capacity; haul_distance_km: pit/shaft-to-plant haul.
MINES = [
    {"mine_id": "BLG-01", "mine_name": "Balaghat", "district": "Balaghat", "state": "Madhya Pradesh",
     "latitude": 21.855, "longitude": 80.235, "mine_type": "Underground", "rated_capacity_tpd": 1600,
     "cluster_id": "BLG", "mn_grade_pct": 44.0, "haul_distance_km": 1.2, "depth_m": 480, "workforce": 1450},
    {"mine_id": "BLG-02", "mine_name": "Ukwa", "district": "Balaghat", "state": "Madhya Pradesh",
     "latitude": 21.968, "longitude": 80.472, "mine_type": "Underground", "rated_capacity_tpd": 520,
     "cluster_id": "BLG", "mn_grade_pct": 40.5, "haul_distance_km": 1.6, "depth_m": 310, "workforce": 620},
    {"mine_id": "BLG-03", "mine_name": "Tirodi", "district": "Balaghat", "state": "Madhya Pradesh",
     "latitude": 21.685, "longitude": 79.720, "mine_type": "Opencast", "rated_capacity_tpd": 450,
     "cluster_id": "BLG", "mn_grade_pct": 38.0, "haul_distance_km": 3.4, "depth_m": 90, "workforce": 380},
    {"mine_id": "BLG-04", "mine_name": "Sitapatore", "district": "Balaghat", "state": "Madhya Pradesh",
     "latitude": 21.735, "longitude": 79.845, "mine_type": "Opencast", "rated_capacity_tpd": 260,
     "cluster_id": "BLG", "mn_grade_pct": 36.5, "haul_distance_km": 2.8, "depth_m": 70, "workforce": 210},
    {"mine_id": "BHD-01", "mine_name": "Dongri Buzurg", "district": "Bhandara", "state": "Maharashtra",
     "latitude": 21.450, "longitude": 79.760, "mine_type": "Opencast", "rated_capacity_tpd": 700,
     "cluster_id": "BHD", "mn_grade_pct": 37.0, "haul_distance_km": 3.9, "depth_m": 110, "workforce": 540},
    {"mine_id": "BHD-02", "mine_name": "Chikla", "district": "Bhandara", "state": "Maharashtra",
     "latitude": 21.515, "longitude": 79.660, "mine_type": "Underground", "rated_capacity_tpd": 400,
     "cluster_id": "BHD", "mn_grade_pct": 39.0, "haul_distance_km": 1.4, "depth_m": 260, "workforce": 460},
    {"mine_id": "NGP-01", "mine_name": "Kandri", "district": "Nagpur", "state": "Maharashtra",
     "latitude": 21.418, "longitude": 79.263, "mine_type": "Underground", "rated_capacity_tpd": 350,
     "cluster_id": "NGP", "mn_grade_pct": 38.5, "haul_distance_km": 1.3, "depth_m": 280, "workforce": 430},
    {"mine_id": "NGP-02", "mine_name": "Munsar", "district": "Nagpur", "state": "Maharashtra",
     "latitude": 21.398, "longitude": 79.232, "mine_type": "Underground", "rated_capacity_tpd": 350,
     "cluster_id": "NGP", "mn_grade_pct": 37.5, "haul_distance_km": 1.5, "depth_m": 240, "workforce": 410},
    {"mine_id": "NGP-03", "mine_name": "Beldongri", "district": "Nagpur", "state": "Maharashtra",
     "latitude": 21.380, "longitude": 79.120, "mine_type": "Opencast", "rated_capacity_tpd": 250,
     "cluster_id": "NGP", "mn_grade_pct": 35.0, "haul_distance_km": 2.6, "depth_m": 60, "workforce": 190},
    {"mine_id": "NGP-04", "mine_name": "Gumgaon", "district": "Nagpur", "state": "Maharashtra",
     "latitude": 21.420, "longitude": 78.950, "mine_type": "Underground", "rated_capacity_tpd": 450,
     "cluster_id": "NGP", "mn_grade_pct": 39.5, "haul_distance_km": 1.4, "depth_m": 300, "workforce": 480},
]

DATA_SOURCES = [
    {"name": "GSI Bhukosh", "url": "https://bhukosh.gsi.gov.in",
     "provides": "1:50k geology, borehole locations, lineament/structure shapefiles",
     "used_for": "Module 1 lithology, lineaments, borehole assays", "status": "SIMULATED_IN_DEMO"},
    {"name": "IBM National Mineral Inventory / Indian Minerals Yearbook", "url": "https://ibm.gov.in",
     "provides": "UNFC reserve/resource classes, grade-wise production statistics",
     "used_for": "Calibrating synthetic production scale and grade ranges", "status": "SIMULATED_IN_DEMO"},
    {"name": "ESA Copernicus Sentinel-2 MSI", "url": "https://dataspace.copernicus.eu",
     "provides": "B2, B4, B8, B11, B12 reflectance (10-20 m)",
     "used_for": "Ferric-iron (B4/B2) and clay (B11/B12) ratios, NDVI, NDWI; map imagery",
     "status": "REAL_IN_VALIDATION"},
    {"name": "ESA Copernicus Sentinel-1 SAR", "url": "https://dataspace.copernicus.eu",
     "provides": "C-band VV/VH backscatter, all-weather",
     "used_for": "Surface roughness/moisture proxy during monsoon cloud cover",
     "status": "SIMULATED_IN_DEMO"},
    {"name": "Copernicus DEM GLO-30 (AWS Open Data)", "url": "https://registry.opendata.aws/copernicus-dem/",
     "provides": "30 m digital surface model",
     "used_for": "Elevation, slope, local relief on the real-data grid", "status": "REAL_IN_VALIDATION"},
    {"name": "ESA WorldCover 2021 v200", "url": "https://esa-worldcover.org",
     "provides": "10 m land cover",
     "used_for": "Bare/built-up fraction for the mining-disturbance check", "status": "REAL_IN_VALIDATION"},
    {"name": "EarthByte Manganese-paleogeography (MIT)", "url": "https://github.com/EarthByte/Manganese-paleogeography",
     "provides": "Global Mn deposit database (Maynard 2010) and 4,264 mindat-derived Mn mineral localities",
     "used_for": "Real Mn locations inside the study area (Tirodi locality; Nagpur-Bhandara district listed, too coarse to train on)",
     "status": "REAL_IN_VALIDATION"},
    {"name": "ISRO Bhuvan / VEDAS (CartoDEM)", "url": "https://bhuvan.nrsc.gov.in",
     "provides": "DEM, land use / land cover",
     "used_for": "Elevation, slope, terrain ruggedness", "status": "SIMULATED_IN_DEMO"},
    {"name": "IMD / NASA POWER / MODIS", "url": "https://power.larc.nasa.gov",
     "provides": "Rainfall, soil moisture, NDVI, land surface temperature",
     "used_for": "Module 2 weather and surface-condition drivers", "status": "SIMULATED_IN_DEMO"},
    {"name": "MOIL public filings (moil.nic.in, environmentclearance.nic.in)", "url": "https://moil.nic.in",
     "provides": "Mine locations, mining method, EIA geotechnical parameters",
     "used_for": "Mine registry (names, districts, methods)", "status": "PUBLIC_REFERENCE"},
]
