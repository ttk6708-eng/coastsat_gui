# Third-party software

This distribution contains CoastSat source code by Kilian Vos and contributors,
https://github.com/kvos/CoastSat, licensed under GNU GPL version 3. See LICENSE.
The desktop wrapper and preprocessing adapter are distributed under GPL-3.0 as well.
Corresponding wrapper source is included alongside the executable. Full development
source, tests, and build instructions are maintained at
https://github.com/ttk6708-eng/coastsat_gui (desktop-preprocessing branch).

Python is obtained from the Python Software Foundation's official `python` NuGet
package (3.12.10). Python's bundled license files are included in env.
GDAL Windows binaries are obtained from Christoph Gohlke's geospatial-wheels
release v2026.8.20. GDAL/PROJ and their bundled dependency notices are in env/Lib/site-packages/osgeo.

Other dependencies include Streamlit, pywebview, NumPy, SciPy, pandas, scikit-image,
scikit-learn, Matplotlib, Pillow, GeoPandas, Astropy, Earth Engine Python API,
PyInstaller, and their transitive dependencies. Their installed package metadata
and bundled license files are retained under env/Lib/site-packages. See
requirements-desktop.lock.txt for the resolved versions and the GDAL download URL.

PyInstaller's bootloader exception permits distribution of the frozen launcher.
No Google credentials, service account files, or user imagery are included.
