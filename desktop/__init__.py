"""Offline-first satellite preprocessing desktop application."""
import os
from pathlib import Path
import importlib.util

# Wheels include PROJ/GDAL data beside osgeo; resolve relative to the active runtime
# so moving the distribution does not retain a build-machine path.
spec = importlib.util.find_spec('osgeo')
if spec and spec.origin:
    data = Path(spec.origin).parent / 'data'
    if (data / 'proj' / 'proj.db').is_file():
        os.environ['PROJ_DATA'] = str(data / 'proj')
        os.environ['PROJ_LIB'] = str(data / 'proj')
        from osgeo import osr
        osr.SetPROJSearchPaths([str(data / 'proj')])
    if (data / 'gdal').is_dir():
        os.environ['GDAL_DATA'] = str(data / 'gdal')
